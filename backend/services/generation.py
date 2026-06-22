import os
import re
import pandas as pd
from typing import Any, List, Optional
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.chains import create_retrieval_chain, create_history_aware_retriever
from langchain_core.documents import Document
from pydantic import BaseModel
from dotenv import load_dotenv

import config
from services.providers import build_chat_model, fallback_candidates

load_dotenv()

# Sentinel marking "the stream ended without yielding anything" (distinct from a
# real empty-string chunk), used by the streaming fallback to tell a clean empty
# response apart from a provider that never started.
_STREAM_EMPTY = object()


def _scan_uploads_for_exact_match(query: str, uploads_dir: Optional[str] = None) -> str:
    """
    Extract numbers/words from the query and scan every CSV/Excel in uploads/
    for rows where ANY column exactly matches that value.
    This guarantees specific ID lookups (EmpID, MovieID, etc.) always work.
    """
    uploads_dir = uploads_dir or str(config.UPLOADS_DIR)
    tokens = list(set(re.findall(r'\b\d+\b', query)))   # numeric IDs like 3833
    if not tokens or not os.path.isdir(uploads_dir):
        return ""

    matched_rows = []
    for fname in os.listdir(uploads_dir):
        fpath = os.path.join(uploads_dir, fname)
        if not os.path.isfile(fpath):
            continue
        ext = fname.lower()
        try:
            if ext.endswith(".csv"):
                df = pd.read_csv(fpath, dtype=str).fillna("")
            elif ext.endswith((".xlsx", ".xls")):
                df = pd.read_excel(fpath, dtype=str).fillna("")
            else:
                continue
            df.columns = [str(c).strip() for c in df.columns]
            for token in tokens:
                mask = df.apply(
                    lambda col: col.astype(str).str.strip() == token, axis=0
                ).any(axis=1)
                for _, row in df[mask].iterrows():
                    parts = [f"{col}: {val}" for col, val in row.items() if str(val).strip()]
                    matched_rows.append("[From {}]\n".format(fname) + " | ".join(parts))
        except Exception as e:
            print(f"[EXACT LOOKUP] {fname}: {e}")

    return "\n\n".join(matched_rows)

# ─────────────────────────────────────────────────────────
# System prompt: matches answer format to question type
# ─────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a precise, expert knowledge assistant. Answer ONLY from the provided context.

### Critical Rules
1. **Match the question format exactly:**
   - Simple question ("What is X?") → 1-3 sentence answer only. No extra sections.
   - "List / explain in points / give steps" → numbered or bullet list.
   - "Explain in detail / describe thoroughly" → structured response with headers.
2. Never add unsolicited sections like Introduction or Conclusion.
3. Use Markdown (bold, code blocks) only when it genuinely helps.
4. If the answer is not in the context, say: *"This information is not present in the uploaded documents."*

Context:
{context}
"""

# ─────────────────────────────────────────────────────────
# Pydantic model for structured multi-query output
# ─────────────────────────────────────────────────────────
class QueryVariations(BaseModel):
    queries: List[str]


# ─────────────────────────────────────────────────────────
# Reciprocal Rank Fusion
# ─────────────────────────────────────────────────────────
def reciprocal_rank_fusion(results: List[List[Document]], k: int = 60) -> List[Document]:
    """
    Merge multiple ranked retrieval lists into one using RRF scoring.
    Higher score = more consistently top-ranked across all query variations.
    """
    scores: dict[str, float] = {}
    doc_map: dict[str, Document] = {}

    for result_list in results:
        for rank, doc in enumerate(result_list):
            key = doc.page_content[:200]          # use content as dedup key
            scores[key] = scores.get(key, 0) + 1 / (rank + k)
            doc_map[key] = doc

    sorted_keys = sorted(scores, key=lambda k: scores[k], reverse=True)
    return [doc_map[key] for key in sorted_keys]


# ─────────────────────────────────────────────────────────
# Main RAG Pipeline
# ─────────────────────────────────────────────────────────
class RAGPipeline:
    def __init__(self, vector_manager):
        self.vector_manager = vector_manager

    # ─── Provider selection + graceful fallback ──────────────────────────
    def _candidates(self, model_name: str, provider: Optional[str]) -> List[tuple]:
        """
        Ordered (provider, model) pairs to try for this request. With fallback
        enabled (the default) it's the chosen provider followed by every other
        configured provider; otherwise just the chosen one (legacy behavior).
        """
        if config.fallback_enabled():
            return fallback_candidates(provider, model_name)
        prov = provider or config.provider_for_model(model_name)
        return [(prov, model_name)]

    @staticmethod
    def _label(provider: str, model: str) -> str:
        """Human-readable 'Provider · model' string for fallback notices."""
        cfg = config.PROVIDERS.get(provider, {})
        return f"{cfg.get('label', provider)} · {model}"

    @staticmethod
    def _join_notice(*parts: str) -> str:
        """Join the non-empty notice fragments into one space-separated string."""
        return " ".join(p for p in parts if p)

    def _build_first_working(self, candidates: List[tuple]):
        """
        Build the first candidate whose chat model *constructs* (i.e. its key /
        config is present). This handles build-time failures — typically a
        missing API key — by moving on to the next configured provider.

        Returns (llm, provider, model, remaining, build_errors): `llm` is None if
        none could be built, `remaining` is the candidates after the chosen one
        (for runtime fallback), `build_errors` collects the per-candidate reasons.
        """
        build_errors: List[str] = []
        for i, (prov, model) in enumerate(candidates):
            try:
                llm = build_chat_model(prov, model)
                return llm, prov, model, candidates[i + 1:], build_errors
            except Exception as e:  # missing key / unknown provider / bad config
                build_errors.append(f"{self._label(prov, model)}: {e}")
        return None, None, None, [], build_errors

    @staticmethod
    def _format_build_error(errors: List[str]) -> str:
        """Turn collected build failures into one user-facing message."""
        if not errors:
            return ("No LLM provider is configured. Add an API key in "
                    "Settings → LLM Providers.")
        if len(errors) == 1:
            # Only one candidate (fallback off, or a single provider) — preserve
            # the factory's precise message, dropping the 'Label · model: ' prefix.
            return errors[0].split(": ", 1)[-1] if ": " in errors[0] else errors[0]
        return ("No usable LLM provider — tried " + "; ".join(errors) +
                ". Add or fix a key in Settings → LLM Providers.")

    def _deserialize_history(self, history: list) -> list:
        """Convert [{role, content}] dicts into LangChain message objects."""
        messages = []
        for msg in history:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "ai":
                messages.append(AIMessage(content=msg["content"]))
        return messages

    def _multi_query_retrieve(self, llm: Any, query: str) -> List[Document]:
        """
        Generate 3 rephrasings of the user query, retrieve docs for each
        with MMR (diversity-aware), then merge via RRF.
        """
        rp = config.retrieval_params()
        retriever = self.vector_manager.as_retriever(
            search_kwargs={
                "k": rp["top_k"],
                "fetch_k": rp["fetch_k"],
                "lambda_mult": rp["mmr_lambda"],
            }
        )
        if retriever is None:
            return []

        # --- Generate query variations ---
        try:
            structured_llm = llm.with_structured_output(QueryVariations)
            prompt = (
                f"Generate 3 different variations of this query to help retrieve "
                f"relevant documents. Return only the 3 alternative queries.\n\n"
                f"Original query: {query}"
            )
            variations = structured_llm.invoke(prompt).queries
        except Exception:
            # Fallback: just use the original query
            variations = [query]

        all_queries = [query] + variations[:3]

        # --- Retrieve for each query variation ---
        all_results: List[List[Document]] = []
        seen_queries: set = set()
        unique_queries: List[str] = []
        for q in all_queries:
            if q in seen_queries:
                continue
            seen_queries.add(q)
            unique_queries.append(q)
            try:
                docs = retriever.invoke(q)              # dense (FAISS + MMR)
                all_results.append(docs)
            except Exception:
                pass

        # --- Hybrid search: add BM25 keyword results as a sparse signal ---
        # Catches exact terms (names, IDs, rare words) that dense search misses.
        # Degrades gracefully to dense-only if BM25 isn't available.
        if rp["bm25_k"] > 0:
            bm25 = self.vector_manager.bm25_retriever(k=rp["bm25_k"])
            if bm25 is not None:
                for q in unique_queries:
                    try:
                        all_results.append(bm25.invoke(q))
                    except Exception:
                        pass

        # --- Merge every dense + sparse ranking with RRF ---
        fused = reciprocal_rank_fusion(all_results)

        # --- Optional Power-mode reranking ---
        # A cross-encoder re-scores the top fused candidates for sharper
        # relevance. Gated to balanced/power (Lite stays fast) and degrades to
        # the plain fusion order if flashrank isn't installed.
        if config.rerank_enabled():
            from services.reranker import rerank
            return rerank(query, fused[:rp["rerank_candidates"]], top_n=rp["final_k"])

        return fused[:rp["final_k"]]   # top fused chunks

    def _rephrase_query_for_history(self, llm: Any, query: str, history: list) -> str:
        """
        If there's conversation history, rewrite the new question so it is
        completely self-contained (history-aware query condensation).
        """
        if not history:
            return query
        messages = [
            SystemMessage(
                content=(
                    "Given the chat history below, rewrite the user's new question "
                    "so it is completely standalone and searchable without needing "
                    "the history. Return ONLY the rewritten question, nothing else."
                )
            )
        ] + history + [HumanMessage(content=f"New question: {query}")]
        try:
            result = llm.invoke(messages)
            return result.content.strip()
        except Exception:
            return query

    def _prepare(
        self,
        query: str,
        model_name: str,
        provider: Optional[str],
        chat_history: Optional[list],
    ) -> tuple:
        """
        Shared retrieval + prompt assembly used by BOTH the streaming and
        non-streaming paths, so the RAG logic lives in exactly one place.

        Returns (llm, messages, sources, early_text, fallback, notice):
          - early_text is a ready-to-send message when there's nothing to answer
            from (no index / no relevant content); messages will be None then.
          - otherwise early_text is None and (llm, messages, sources) are ready.
          - fallback: remaining (provider, model) pairs to try if `llm` fails at
            generation time (empty when fallback is off or `llm` is the last one).
          - notice: a user-facing note when the originally-chosen provider was
            unavailable and a fallback was selected at build time (else "").
        May raise ValueError (e.g. no provider has a usable key) — callers
        translate that into a user-facing error.
        """
        if not self.vector_manager.is_loaded():
            return (
                None, None, [],
                "**No documents indexed yet.** Please upload files first via the Ingest Knowledge panel.",
                [], "",
            )

        candidates = self._candidates(model_name, provider)
        llm, prov, model, fallback, build_errors = self._build_first_working(candidates)
        if llm is None:
            raise ValueError(self._format_build_error(build_errors))

        # If the chosen provider couldn't be built and we fell back, tell the user.
        notice = ""
        if (prov, model) != candidates[0]:
            notice = (
                f"{self._label(*candidates[0])} is unavailable, so this answer "
                f"was generated with {self._label(prov, model)}."
            )

        # 1. Deserialize history
        history_messages = self._deserialize_history(chat_history or [])

        # 2. History-aware query condensation
        search_query = self._rephrase_query_for_history(llm, query, history_messages)

        # 3. Hybrid (dense + BM25) multi-query retrieval fused with RRF
        fused_docs = self._multi_query_retrieve(llm, search_query)

        if not fused_docs:
            return (
                llm, None, [],
                "**No relevant content found** in the uploaded documents for your question.",
                [], "",
            )

        # 4. Build sources list for frontend transparency
        seen = set()
        sources = []
        for i, doc in enumerate(fused_docs):
            meta = doc.metadata or {}
            fname = meta.get("source", "Unknown")
            preview = doc.page_content[:120].replace("\n", " ").strip()
            key = (fname, preview[:40])
            if key not in seen:
                seen.add(key)
                # Human-readable location for citations, when we tracked it at
                # index time (page N for PDFs, rows X-Y for tables).
                location = ""
                if meta.get("page") is not None:
                    location = f"page {meta['page']}"
                elif meta.get("rows"):
                    location = f"rows {meta['rows']}"
                sources.append({
                    "file": fname,
                    "chunk": i + 1,
                    "location": location,
                    "preview": preview,
                    # Full chunk text (capped) so the UI can show the exact
                    # context a citation came from on click. Capped to keep
                    # chat-history rows from bloating.
                    "text": doc.page_content[:4000],
                })

        # 5. Run exact CSV/Excel lookup for numeric IDs (e.g. "emp id 3833")
        #    and PREPEND those rows to the context so the LLM sees them first.
        exact_match_text = _scan_uploads_for_exact_match(query)
        faiss_context = "\n\n---\n\n".join(d.page_content for d in fused_docs)
        if exact_match_text:
            context_text = (
                "=== EXACT MATCH (direct record lookup) ===\n"
                + exact_match_text
                + "\n\n=== ADDITIONAL CONTEXT (semantic search) ===\n"
                + faiss_context
            )
        else:
            context_text = faiss_context

        messages = (
            [SystemMessage(content=SYSTEM_PROMPT.format(context=context_text))]
            + history_messages
            + [HumanMessage(content=query)]
        )
        return llm, messages, sources, None, fallback, notice

    def generate_response(
        self,
        query: str,
        model_name: str = config.DEFAULT_MODEL,
        chat_history: Optional[list] = None,
        provider: Optional[str] = None,
    ) -> tuple:
        """
        Returns (answer: str, sources: list[dict], notice: str). Non-streaming.
        `notice` is "" unless a provider fallback happened (build- or run-time).
        """
        llm, messages, sources, early_text, fallback, notice = self._prepare(
            query, model_name, provider, chat_history
        )
        if early_text is not None:
            return (early_text, [], "")
        answer, run_notice = self._invoke_with_fallback(llm, messages, fallback)
        return (answer, sources, self._join_notice(notice, run_notice))

    def _invoke_with_fallback(self, llm: Any, messages: list, fallback: List[tuple]) -> tuple:
        """
        Invoke `llm`; on any runtime error (rate-limit, network, provider down)
        try each fallback (provider, model) in turn. Returns (answer, notice).
        Raises ValueError only when every candidate fails.
        """
        try:
            return llm.invoke(messages).content, ""
        except Exception as primary_err:
            errors = [str(primary_err)]
            for prov, model in fallback:
                try:
                    alt = build_chat_model(prov, model)
                    content = alt.invoke(messages).content
                    return content, (
                        f"The selected model failed, so this answer was generated "
                        f"with {self._label(prov, model)}."
                    )
                except Exception as e:
                    errors.append(str(e))
            raise ValueError(
                "The language model request failed and no fallback provider "
                "succeeded: " + " | ".join(errors)
            )

    def generate_response_stream(
        self,
        query: str,
        model_name: str = config.DEFAULT_MODEL,
        chat_history: Optional[list] = None,
        provider: Optional[str] = None,
    ):
        """
        Generator of SSE-friendly event dicts for token streaming:
          {"type": "sources", "sources": [...]}   (once, before the answer)
          {"type": "notice", "content": "..."}     (at most once, if a fallback ran)
          {"type": "token",   "content": "..."}    (many)
          {"type": "done"}                          (once, at the end)
        Retrieval runs first (fast, non-streamed); only the final LLM answer
        streams token-by-token. ValueError from _prepare propagates to the
        endpoint, which emits an {"type":"error"} event.
        """
        llm, messages, sources, early_text, fallback, notice = self._prepare(
            query, model_name, provider, chat_history
        )
        if early_text is not None:
            yield {"type": "token", "content": early_text}
            yield {"type": "done"}
            return

        yield {"type": "sources", "sources": sources}
        yield from self._stream_with_fallback(llm, messages, fallback, notice)

    def _stream_with_fallback(self, llm: Any, messages: list, fallback: List[tuple], build_notice: str):
        """
        Stream tokens from `llm`; if a provider fails *before its first token*,
        transparently fall back to the next configured one. A mid-stream failure
        (after tokens were already sent) can't be retried without duplicating
        output, so it surfaces as an `error` event. Emits a `notice` event when a
        fallback (build-time or runtime) was used.
        """
        attempts = [(None, llm)] + [(cand, None) for cand in fallback]
        errors: List[str] = []
        for idx, (cand, prebuilt) in enumerate(attempts):
            try:
                model_obj = prebuilt or build_chat_model(cand[0], cand[1])
                stream = model_obj.stream(messages)
                first = next(stream, _STREAM_EMPTY)   # may raise: auth / rate-limit / offline
            except Exception as e:
                errors.append(str(e))
                continue

            # This attempt started — announce any fallback, then stream its tokens.
            notice = build_notice
            if idx > 0:
                notice = self._join_notice(
                    build_notice,
                    f"The selected model failed, so this answer was generated "
                    f"with {self._label(cand[0], cand[1])}.",
                )
            if notice:
                yield {"type": "notice", "content": notice}

            try:
                if first is not _STREAM_EMPTY:
                    text = getattr(first, "content", "") or ""
                    if text:
                        yield {"type": "token", "content": text}
                for chunk in stream:
                    text = getattr(chunk, "content", "") or ""
                    if text:
                        yield {"type": "token", "content": text}
            except Exception as e:
                # Failed after streaming began — can't restart cleanly.
                yield {"type": "error", "detail": f"The model stopped mid-response: {e}"}
                return
            yield {"type": "done"}
            return

        # Nothing started successfully.
        yield {
            "type": "error",
            "detail": "The language model request failed and no fallback provider "
                      "succeeded: " + " | ".join(errors),
        }

