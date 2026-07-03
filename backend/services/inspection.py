"""
Retrieval Inspector — an opt-in, zero-overhead-when-off trace of the RAG pipeline.

The pipeline (services/generation.py) computes a lot of intermediate state on the
way to an answer — the history-rewritten query, the generated multi-query
variations, the per-query dense (FAISS) and sparse (BM25) hits, the RRF-merged
ranking, the reranker output, and the final context string actually sent to the
LLM — and then throws all of it away. That makes the system a black box: there's
no way to see *why* a given answer was produced, or to debug bad retrieval.

`RetrievalTrace` is a tiny collector that the pipeline threads through as an
OPTIONAL argument. When no trace is passed (the default), the pipeline behaves
exactly as before — not a single extra call or allocation. When a trace *is*
passed (because the user turned the Retrieval Inspector on in Settings), each
stage records a compact, capped snapshot into it, and the streaming endpoint
emits the finished trace as one extra `inspection` SSE event after the answer.

Design rules
------------
- **Never raise.** Recording is best-effort; a bug in tracing must never be able
  to break an answer. Every public method is wrapped so a failure is swallowed.
- **Bounded size.** Chunk text is capped (PREVIEW_CHARS) so the JSON payload stays
  small even with large chunks — the Inspector shows previews, not whole documents.
- **Serializable.** `to_dict()` returns plain JSON-friendly types, ready to drop
  straight into an SSE event.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from langchain_core.documents import Document

logger = logging.getLogger(__name__)

# Per-chunk preview cap. Enough to recognise a chunk without bloating the payload
# (the Sources panel already carries fuller text for citations).
PREVIEW_CHARS = 600


def _doc_preview(doc: Document, rank: Optional[int] = None,
                 score: Optional[float] = None) -> dict:
    """Compact, JSON-safe snapshot of one retrieved chunk."""
    meta = getattr(doc, "metadata", None) or {}
    text = getattr(doc, "page_content", "") or ""
    out: dict[str, Any] = {
        "source": meta.get("source", "Unknown"),
        "preview": text[:PREVIEW_CHARS].replace("\n", " ").strip(),
        "chars": len(text),
    }
    # Location metadata (page / rows), when it was tracked at index time.
    if meta.get("page") is not None:
        out["location"] = f"page {meta['page']}"
    elif meta.get("rows"):
        out["location"] = f"rows {meta['rows']}"
    if rank is not None:
        out["rank"] = rank
    if score is not None:
        out["score"] = round(float(score), 5)
    return out


class RetrievalTrace:
    """
    Accumulates a stage-by-stage record of one retrieval + generation request.

    Passed as an optional `trace=` into the pipeline. All setters no-op-safely on
    any error so tracing can never break the answer path.
    """

    def __init__(self) -> None:
        self.data: dict[str, Any] = {
            "original_query": None,      # the raw user question
            "rewritten_query": None,     # history-aware condensation (or same)
            "multi_queries": [],         # the query variations actually searched
            "dense_by_query": [],        # [{query, hits:[chunk...]}] FAISS/MMR per query
            "sparse_by_query": [],       # [{query, hits:[chunk...]}] BM25 per query
            "fused": [],                 # RRF-merged ranking (chunk previews, in order)
            "reranked": None,            # reranker output, or None if rerank was off
            "rerank_enabled": False,
            "exact_match": None,         # CSV/Excel exact-lookup text (capped), or None
            "final_context_chars": None, # size of the context string sent to the LLM
            "final_context_preview": None,
            "budget": None,              # resolved prompt budget in force
            "timings_ms": {},            # stage -> milliseconds
            "tokens": None,              # {prompt, completion, total, estimated:bool}
            "provider": None,            # 'Provider · model' that answered
        }

    # ---- setters (each best-effort; never raise) -----------------------------

    def _safe(self, fn) -> None:
        try:
            fn()
        except Exception as e:  # pragma: no cover - defensive
            logger.debug(f"RetrievalTrace record skipped: {e}")

    def set_query_rewrite(self, original: str, rewritten: str) -> None:
        self._safe(lambda: self.data.update({
            "original_query": original,
            "rewritten_query": rewritten,
        }))

    def set_multi_queries(self, multi: List[str]) -> None:
        self._safe(lambda: self.data.update({"multi_queries": list(multi)}))

    def add_dense(self, query: str, docs: List[Document]) -> None:
        self._safe(lambda: self.data["dense_by_query"].append({
            "query": query,
            "hits": [_doc_preview(d, rank=i + 1) for i, d in enumerate(docs)],
        }))

    def add_sparse(self, query: str, docs: List[Document]) -> None:
        self._safe(lambda: self.data["sparse_by_query"].append({
            "query": query,
            "hits": [_doc_preview(d, rank=i + 1) for i, d in enumerate(docs)],
        }))

    def set_fused(self, docs: List[Document]) -> None:
        self._safe(lambda: self.data.update({
            "fused": [_doc_preview(d, rank=i + 1) for i, d in enumerate(docs)],
        }))

    def set_reranked(self, docs: List[Document]) -> None:
        self._safe(lambda: self.data.update({
            "reranked": [_doc_preview(d, rank=i + 1) for i, d in enumerate(docs)],
            "rerank_enabled": True,
        }))

    def set_exact_match(self, text: str) -> None:
        self._safe(lambda: self.data.update({
            "exact_match": (text[:PREVIEW_CHARS] if text else None),
        }))

    def set_final_context(self, context_text: str, budget: dict) -> None:
        self._safe(lambda: self.data.update({
            "final_context_chars": len(context_text or ""),
            "final_context_preview": (context_text or "")[:PREVIEW_CHARS],
            "budget": dict(budget) if budget else None,
        }))

    def set_provider(self, label: str) -> None:
        self._safe(lambda: self.data.update({"provider": label}))

    def add_timing(self, stage: str, ms: float) -> None:
        self._safe(lambda: self.data["timings_ms"].update({stage: round(ms, 1)}))

    def set_tokens(self, usage: Optional[dict]) -> None:
        self._safe(lambda: self.data.update({"tokens": usage}))

    def to_dict(self) -> dict:
        return self.data
