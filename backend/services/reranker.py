"""
Cross-encoder reranking (Power-gated, optional).

After dense + BM25 fusion produces a candidate set, a cross-encoder re-scores
each (query, chunk) pair *jointly* — far sharper relevance than the bi-encoder
similarity used for retrieval. The catch is cost: it runs a small transformer
per candidate, so it's gated behind balanced/power modes (see
config.rerank_enabled()).

We use `flashrank` — a tiny ONNX cross-encoder runner (a few MB, CPU-friendly,
no torch). It's an OPTIONAL dependency: if it isn't installed, or the model
can't load, `rerank()` returns the candidates untouched so chat never breaks.
The model downloads once into config.MODELS_DIR.
"""

from __future__ import annotations

from typing import List

from langchain_core.documents import Document

import config
import logging

logger = logging.getLogger(__name__)

# Lazily-built singletons. _ranker is the flashrank Ranker; _disabled latches
# True after a failed load so we don't retry (and re-log) on every query.
_ranker = None
_disabled = False


def is_available() -> bool:
    """
    True if the `flashrank` package is importable (the model itself loads lazily
    on first use). Lets the UI warn when reranking is switched on but the
    optional dependency isn't installed (e.g. a fresh Lite install).
    """
    import importlib.util

    return importlib.util.find_spec("flashrank") is not None


def _get_ranker():
    """Build (once) and return the flashrank Ranker, or None if unavailable."""
    global _ranker, _disabled
    if _ranker is not None:
        return _ranker
    if _disabled:
        return None
    try:
        from flashrank import Ranker  # optional dependency

        config.ensure_dirs()
        _ranker = Ranker(
            model_name=config.RERANK_MODEL,
            cache_dir=str(config.MODELS_DIR),
        )
        logger.info(f"Loaded cross-encoder '{config.RERANK_MODEL}'")
        return _ranker
    except Exception as e:
        _disabled = True
        logger.warning(
            f"Reranking disabled (falling back to fusion order): {e}. "
            f"Install with `pip install flashrank` to enable reranking."
        )
        return None


def rerank(query: str, docs: List[Document], top_n: int) -> List[Document]:
    """
    Re-score `docs` against `query` with a cross-encoder and return the top_n.

    Pure pass-through (returns docs[:top_n] in their existing order) if the
    reranker isn't available or anything goes wrong — reranking must never be
    able to break the answer path.
    """
    if not docs:
        return docs
    ranker = _get_ranker()
    if ranker is None:
        return docs[:top_n]

    try:
        from flashrank import RerankRequest

        passages = [{"id": i, "text": d.page_content} for i, d in enumerate(docs)]
        results = ranker.rerank(RerankRequest(query=query, passages=passages))
        # flashrank returns passages sorted by descending relevance score.
        ordered = [docs[r["id"]] for r in results if 0 <= r["id"] < len(docs)]
        # Safety net: if mapping dropped anything, append the rest in original order.
        if len(ordered) < len(docs):
            seen = {id(d) for d in ordered}
            ordered += [d for d in docs if id(d) not in seen]
        return ordered[:top_n]
    except Exception as e:
        logger.warning(f"Reranker scoring failed, using fusion order: {e}")
        return docs[:top_n]
