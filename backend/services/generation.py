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
from services.providers import build_chat_model

load_dotenv()


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

    def _build_llm(self, model_name: str, provider: Optional[str] = None) -> Any:
        """
        Build a chat model via the provider factory. `provider` may be None,
        in which case it's resolved from the model id. Raises ValueError with a
        user-facing message if the chosen provider has no key configured.
        """
        return build_chat_model(provider, model_name)

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

        Returns (llm, messages, sources, early_text):
          - early_text is a ready-to-send message when there's nothing to answer
            from (no index / no relevant content); messages will be None then.
          - otherwise early_text is None and (llm, messages, sources) are ready.
        May raise ValueError from _build_llm (e.g. missing API key) — callers
        translate that into a user-facing error.
        """
        if not self.vector_manager.is_loaded():
            return (
                None, None, [],
                "**No documents indexed yet.** Please upload files first via the Ingest Knowledge panel.",
            )

        llm = self._build_llm(model_name, provider)

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
        return llm, messages, sources, None

    def generate_response(
        self,
        query: str,
        model_name: str = config.DEFAULT_MODEL,
        chat_history: Optional[list] = None,
        provider: Optional[str] = None,
    ) -> tuple:
        """Returns (answer: str, sources: list[dict]). Non-streaming."""
        llm, messages, sources, early_text = self._prepare(
            query, model_name, provider, chat_history
        )
        if early_text is not None:
            return (early_text, [])
        result = llm.invoke(messages)
        return (result.content, sources)

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
          {"type": "token",   "content": "..."}    (many)
          {"type": "done"}                          (once, at the end)
        Retrieval runs first (fast, non-streamed); only the final LLM answer
        streams token-by-token. ValueError from _prepare propagates to the
        endpoint, which emits an {"type":"error"} event.
        """
        llm, messages, sources, early_text = self._prepare(
            query, model_name, provider, chat_history
        )
        if early_text is not None:
            yield {"type": "token", "content": early_text}
            yield {"type": "done"}
            return

        yield {"type": "sources", "sources": sources}
        for chunk in llm.stream(messages):
            text = getattr(chunk, "content", "") or ""
            if text:
                yield {"type": "token", "content": text}
        yield {"type": "done"}

