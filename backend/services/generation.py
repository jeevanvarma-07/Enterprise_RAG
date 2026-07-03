import logging
import os
import random
import re
import time
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
from services.providers import (
    build_chat_model,
    fallback_candidates,
    extract_usage,
    estimate_tokens,
)

load_dotenv()

logger = logging.getLogger(__name__)


def _now_ms() -> float:
    """Monotonic millisecond clock for stage timings (never negative/jumpy)."""
    return time.perf_counter() * 1000.0


# Transient error reasons that are worth a same-provider retry (a brief backoff
# may clear them) before falling back to a different provider. Auth/model errors
# are excluded — retrying those just wastes time.
_TRANSIENT_REASONS = {"rate limit reached", "request timed out", "network error"}

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
            logger.warning(f"Exact-lookup scan failed for {fname}: {e}")

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
def reciprocal_rank_fusion(
    results: List[List[Document]], k: int = 60, return_scores: bool = False
):
    """
    Merge multiple ranked retrieval lists into one using RRF scoring.
    Higher score = more consistently top-ranked across all query variations.

    By default returns the merged `List[Document]` (unchanged contract for all
    existing callers). With `return_scores=True` it returns a list of
    `(Document, score)` pairs instead — used only by the Retrieval Inspector so
    it can show *why* each chunk ranked where it did.
    """
    scores: dict[str, float] = {}
    doc_map: dict[str, Document] = {}

    for result_list in results:
        for rank, doc in enumerate(result_list):
            key = doc.page_content[:200]          # use content as dedup key
            scores[key] = scores.get(key, 0) + 1 / (rank + k)
            doc_map[key] = doc

    sorted_keys = sorted(scores, key=lambda k: scores[k], reverse=True)
    if return_scores:
        return [(doc_map[key], scores[key]) for key in sorted_keys]
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
    def _error_reason(err: str) -> str:
        """
        Condense a raw provider exception into a short, user-facing reason so a
        fallback notice can say *why* the chosen model failed (e.g. a wrong key)
        instead of a generic "failed". Best-effort string matching — defaults to
        a plain "error" when nothing recognisable is present.
        """
        e = (err or "").lower()
        if any(s in e for s in ("401", "unauthorized", "invalid api key", "invalid_api_key",
                                "authentication", "no api key", "incorrect api key")):
            return "invalid or missing API key"
        if any(s in e for s in ("402", "payment required", "insufficient balance",
                                "insufficient_quota", "no balance", "billing")):
            return "no account balance — this provider needs paid credit"
        if any(s in e for s in ("429", "rate limit", "rate_limit", "quota", "tokens per minute", "tpm")):
            return "rate limit reached"
        if any(s in e for s in ("404", "not found", "does not exist", "decommission", "no such model")):
            return "model not available"
        if any(s in e for s in ("timeout", "timed out")):
            return "request timed out"
        if any(s in e for s in ("connection", "network", "getaddrinfo", "ssl", "unreachable")):
            return "network error"
        return "error"

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

    def _multi_query_retrieve(self, llm: Any, query: str, trace=None) -> List[Document]:
        """
        Generate 3 rephrasings of the user query, retrieve docs for each
        with MMR (diversity-aware), then merge via RRF.

        `trace` (a services.inspection.RetrievalTrace or None) optionally records
        each stage for the Retrieval Inspector. When None — the default — this
        behaves exactly as before with no extra work.
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
                if trace is not None:
                    trace.add_dense(q, docs)
            except Exception:
                pass

        if trace is not None:
            trace.set_multi_queries(unique_queries)

        # --- Hybrid search: add BM25 keyword results as a sparse signal ---
        # Catches exact terms (names, IDs, rare words) that dense search misses.
        # Degrades gracefully to dense-only if BM25 isn't available.
        if rp["bm25_k"] > 0:
            bm25 = self.vector_manager.bm25_retriever(k=rp["bm25_k"])
            if bm25 is not None:
                for q in unique_queries:
                    try:
                        hits = bm25.invoke(q)
                        all_results.append(hits)
                        if trace is not None:
                            trace.add_sparse(q, hits)
                    except Exception:
                        pass

        # --- Merge every dense + sparse ranking with RRF ---
        if trace is not None:
            scored = reciprocal_rank_fusion(all_results, return_scores=True)
            fused = [d for d, _ in scored]
            trace.set_fused(fused)
        else:
            fused = reciprocal_rank_fusion(all_results)

        # --- Optional Power-mode reranking ---
        # A cross-encoder re-scores the top fused candidates for sharper
        # relevance. Gated to balanced/power (Lite stays fast) and degrades to
        # the plain fusion order if flashrank isn't installed.
        if config.rerank_enabled():
            from services.reranker import rerank
            reranked = rerank(query, fused[:rp["rerank_candidates"]], top_n=rp["final_k"])
            if trace is not None:
                trace.set_reranked(reranked)
            return reranked

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
        trace=None,
    ) -> tuple:
        """
        Shared retrieval + prompt assembly used by BOTH the streaming and
        non-streaming paths, so the RAG logic lives in exactly one place.

        Returns (llm, messages, sources, early_text, fallback, notice, primary_label):
          - early_text is a ready-to-send message when there's nothing to answer
            from (no index / no relevant content); messages will be None then.
          - otherwise early_text is None and (llm, messages, sources) are ready.
          - fallback: remaining (provider, model) pairs to try if `llm` fails at
            generation time (empty when fallback is off or `llm` is the last one).
          - notice: a user-facing note when the originally-chosen provider was
            unavailable and a fallback was selected at build time (else "").
          - primary_label: 'Provider · model' of the model that actually built,
            so a runtime-fallback notice can name which model failed ("" on the
            early-return paths, where no LLM is invoked).
        May raise ValueError (e.g. no provider has a usable key) — callers
        translate that into a user-facing error.
        """
        if not self.vector_manager.is_loaded():
            return (
                None, None, [],
                "**No documents indexed yet.** Please upload files first via the Ingest Knowledge panel.",
                [], "", "",
            )

        candidates = self._candidates(model_name, provider)
        llm, prov, model, fallback, build_errors = self._build_first_working(candidates)
        if llm is None:
            raise ValueError(self._format_build_error(build_errors))

        # The model actually built (the one a runtime failure would be about), so
        # a fallback notice can name *which* model failed.
        primary_label = self._label(prov, model)
        if trace is not None:
            trace.set_provider(primary_label)

        # If the chosen provider couldn't be built and we fell back, tell the user.
        notice = ""
        if (prov, model) != candidates[0]:
            notice = (
                f"{self._label(*candidates[0])} is unavailable, so this answer "
                f"was generated with {self._label(prov, model)}."
            )

        # Prompt-size budget: cap history + context so a single request can't
        # exceed the provider's tokens-per-minute limit (the 413 on Groq's free
        # tier). See config.prompt_budget().
        budget = config.prompt_budget()

        # 1. Deserialize history, then trim to the configured sliding window so
        #    a long conversation isn't re-sent in full on every turn.
        history_messages = self._deserialize_history(chat_history or [])
        cap = budget["history_messages"]
        history_messages = history_messages[-cap:] if cap else []

        # 2. History-aware query condensation
        search_query = self._rephrase_query_for_history(llm, query, history_messages)
        if trace is not None:
            trace.set_query_rewrite(query, search_query)

        # 3. Hybrid (dense + BM25) multi-query retrieval fused with RRF
        _t_retr = _now_ms()
        fused_docs = self._multi_query_retrieve(llm, search_query, trace=trace)
        if trace is not None:
            trace.add_timing("retrieval", _now_ms() - _t_retr)

        if not fused_docs:
            return (
                llm, None, [],
                "**No relevant content found** in the uploaded documents for your question.",
                [], "", "",
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
        if trace is not None:
            trace.set_exact_match(exact_match_text)
        faiss_context = "\n\n---\n\n".join(d.page_content for d in fused_docs)

        # Trim the retrieved context to the configured character budget so a
        # single request can't exceed the provider's tokens-per-minute limit
        # (the 413 "Request too large" on Groq's free tier). The exact-match
        # rows are the precise hit, so they get first claim on the budget; the
        # semantic context fills whatever's left. BOTH are capped, so the total
        # never exceeds the budget even when an exact match is itself huge
        # (e.g. a big CSV/Excel record dump).
        ctx_budget = budget["context_chars"]
        if exact_match_text:
            exact = exact_match_text[:ctx_budget]
            remaining = ctx_budget - len(exact)
            context_text = "=== EXACT MATCH (direct record lookup) ===\n" + exact
            if remaining > 200 and faiss_context:
                context_text += (
                    "\n\n=== ADDITIONAL CONTEXT (semantic search) ===\n"
                    + faiss_context[:remaining]
                )
        else:
            context_text = faiss_context[:ctx_budget]

        if trace is not None:
            trace.set_final_context(context_text, budget)

        messages = (
            [SystemMessage(content=SYSTEM_PROMPT.format(context=context_text))]
            + history_messages
            + [HumanMessage(content=query)]
        )
        return llm, messages, sources, None, fallback, notice, primary_label

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
        llm, messages, sources, early_text, fallback, notice, primary_label = self._prepare(
            query, model_name, provider, chat_history
        )
        if early_text is not None:
            return (early_text, [], "")
        answer, run_notice = self._invoke_with_fallback(llm, messages, fallback, primary_label)
        return (answer, sources, self._join_notice(notice, run_notice))

    def _retry_transient(self, fn, attempts: int = 2, base_delay: float = 0.4):
        """
        Call `fn()`; if it fails with a *transient* error (rate-limit / timeout /
        network — see _TRANSIENT_REASONS), wait with exponential backoff + jitter
        and retry the SAME call, up to `attempts` times total, BEFORE the caller
        moves on to a different provider. Non-transient errors (bad key, unknown
        model) re-raise immediately — retrying those just wastes the user's time.

        Bounded and jittered so a flaky provider can't stall a request for long.
        Returns fn()'s result, or re-raises the final exception.
        """
        last_err: Optional[Exception] = None
        for i in range(max(1, attempts)):
            try:
                return fn()
            except Exception as e:
                last_err = e
                reason = self._error_reason(str(e))
                if reason not in _TRANSIENT_REASONS or i == attempts - 1:
                    raise
                delay = base_delay * (2 ** i) + random.uniform(0, base_delay)
                logger.info(
                    f"Transient LLM error ({reason}); retrying in {delay:.1f}s "
                    f"(attempt {i + 1}/{attempts})."
                )
                time.sleep(delay)
        raise last_err  # pragma: no cover - loop always returns or raises

    def _invoke_with_fallback(
        self, llm: Any, messages: list, fallback: List[tuple], primary_label: str = ""
    ) -> tuple:
        """
        Invoke `llm`; on any runtime error (rate-limit, network, provider down)
        try each fallback (provider, model) in turn. Returns (answer, notice).
        The notice names the model that failed (`primary_label`) and a short
        reason. Raises ValueError only when every candidate fails.

        Each attempt first retries transiently (see `_retry_transient`) so a brief
        rate-limit/timeout blip doesn't needlessly burn a provider.
        """
        try:
            return self._retry_transient(lambda: llm.invoke(messages)).content, ""
        except Exception as primary_err:
            errors = [str(primary_err)]
            failed = primary_label or "The selected model"
            reason = self._error_reason(str(primary_err))
            for prov, model in fallback:
                try:
                    alt = build_chat_model(prov, model)
                    content = self._retry_transient(lambda: alt.invoke(messages)).content
                    return content, (
                        f"{failed} failed ({reason}), so this answer was generated "
                        f"with {self._label(prov, model)} instead."
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
        inspect: bool = False,
    ):
        """
        Generator of SSE-friendly event dicts for token streaming:
          {"type": "sources", "sources": [...]}      (once, before the answer)
          {"type": "notice", "content": "..."}        (at most once, if a fallback ran)
          {"type": "token",   "content": "..."}       (many)
          {"type": "inspection", "data": {...}}        (once, only when inspect=True)
          {"type": "done", "metrics": {...}}           (once, at the end)
        Retrieval runs first (fast, non-streamed); only the final LLM answer
        streams token-by-token. ValueError from _prepare propagates to the
        endpoint, which emits an {"type":"error"} event.

        `inspect` (driven by the default-off `retrieval_inspector` setting) turns
        on the Retrieval Inspector: every pipeline stage is recorded into a trace
        and emitted as one extra `inspection` event. When off, the trace is never
        created and this behaves exactly as before.
        """
        trace = None
        if inspect:
            from services.inspection import RetrievalTrace
            trace = RetrievalTrace()

        t0 = _now_ms()
        llm, messages, sources, early_text, fallback, notice, primary_label = self._prepare(
            query, model_name, provider, chat_history, trace=trace
        )
        if early_text is not None:
            yield {"type": "token", "content": early_text}
            if trace is not None:
                trace.add_timing("total", _now_ms() - t0)
                yield {"type": "inspection", "data": trace.to_dict()}
            yield {"type": "done"}
            return

        yield {"type": "sources", "sources": sources}

        gen_start = _now_ms()
        answer, usage = yield from self._stream_with_fallback(
            llm, messages, fallback, notice, primary_label
        )
        if answer is None:
            # A terminal `error` event was already emitted — nothing more to send.
            return

        gen_ms = _now_ms() - gen_start
        total_ms = _now_ms() - t0
        # Streaming providers usually don't report token usage; fall back to a
        # clearly-labelled estimate so the dashboard/inspector still has numbers.
        if usage is None:
            prompt_text = "".join(getattr(m, "content", "") or "" for m in messages)
            p, c = estimate_tokens(prompt_text), estimate_tokens(answer)
            usage = {"prompt": p, "completion": c, "total": p + c, "estimated": True}

        metrics = {
            "provider": primary_label,
            "tokens": usage,
            "retrieval_ms": round(gen_start - t0, 1),   # prep + retrieval time
            "generation_ms": round(gen_ms, 1),
            "total_ms": round(total_ms, 1),
        }
        if trace is not None:
            trace.add_timing("generation", gen_ms)
            trace.add_timing("total", total_ms)
            trace.set_tokens(usage)
            yield {"type": "inspection", "data": trace.to_dict()}
        yield {"type": "done", "metrics": metrics}

    def _stream_with_fallback(
        self, llm: Any, messages: list, fallback: List[tuple], build_notice: str,
        primary_label: str = "",
    ):
        """
        Stream tokens from `llm`; if a provider fails *before its first token*,
        transparently fall back to the next configured one (each provider first
        retries transient blips via `_retry_transient`). A mid-stream failure
        (after tokens were already sent) can't be retried without duplicating
        output, so it surfaces as an `error` event. Emits a `notice` event when a
        fallback (build-time or runtime) was used.

        Returns `(answer_text, usage)` on success — the accumulated answer and any
        provider-reported token usage (or None) — so the caller can record
        telemetry. Returns `(None, None)` after emitting an `error` event.
        """
        attempts = [(None, llm)] + [(cand, None) for cand in fallback]
        errors: List[str] = []
        for idx, (cand, prebuilt) in enumerate(attempts):
            try:
                model_obj = prebuilt or build_chat_model(cand[0], cand[1])

                def _open_stream():
                    s = model_obj.stream(messages)
                    return s, next(s, _STREAM_EMPTY)  # may raise: auth/rate-limit/offline

                stream, first = self._retry_transient(_open_stream)
            except Exception as e:
                errors.append(str(e))
                continue

            # This attempt started — announce any fallback, then stream its tokens.
            notice = build_notice
            if idx > 0:
                failed = primary_label or "The selected model"
                reason = self._error_reason(errors[0] if errors else "")
                notice = self._join_notice(
                    build_notice,
                    f"{failed} failed ({reason}), so this answer was generated "
                    f"with {self._label(cand[0], cand[1])} instead.",
                )
            if notice:
                yield {"type": "notice", "content": notice}

            answer_parts: List[str] = []
            usage: Optional[dict] = None
            try:
                if first is not _STREAM_EMPTY:
                    usage = extract_usage(first) or usage
                    text = getattr(first, "content", "") or ""
                    if text:
                        answer_parts.append(text)
                        yield {"type": "token", "content": text}
                for chunk in stream:
                    usage = extract_usage(chunk) or usage
                    text = getattr(chunk, "content", "") or ""
                    if text:
                        answer_parts.append(text)
                        yield {"type": "token", "content": text}
            except Exception as e:
                # Failed after streaming began — can't restart cleanly.
                yield {"type": "error", "detail": f"The model stopped mid-response: {e}"}
                return None, None
            return "".join(answer_parts), usage

        # Nothing started successfully.
        yield {
            "type": "error",
            "detail": "The language model request failed and no fallback provider "
                      "succeeded: " + " | ".join(errors),
        }
        return None, None

