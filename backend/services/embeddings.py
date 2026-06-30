"""
Embedding backend abstraction.

One place to build the sentence-embedding model used for both indexing and
querying. The default is HuggingFace `sentence-transformers` (which pulls in
torch, ~2 GB); the Lite profile uses an ONNX backend (`fastembed`, no torch).
This indirection lets us swap backends WITHOUT touching the rest of the code,
and lets us stamp which backend built an index so we can warn on a mismatch —
vectors produced by different models are not comparable, so silently mixing them
would quietly wreck retrieval.

Both backends use `all-MiniLM-L6-v2` (same 384-dim space, verified parity), so
falling back from one to the other never breaks an existing index.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Tuple

import config

logger = logging.getLogger(__name__)

_FASTEMBED = ("fastembed", "onnx")


@lru_cache(maxsize=None)
def _is_importable(backend: str) -> bool:
    """
    Whether the heavy dependency behind a backend can actually be imported.

    Cached: availability can't change within a process, and a failed import is
    otherwise re-attempted on every call. Used to resolve the configured backend
    to one that is really installed (the Lite build ships `fastembed` and
    excludes torch, so a setting that still says `sentence-transformers` must
    transparently fall back instead of crashing on a fresh install).
    """
    try:
        if backend in _FASTEMBED:
            import fastembed  # noqa: F401
        else:
            import sentence_transformers  # noqa: F401
        return True
    except Exception:
        return False


def _effective_backend(requested: str) -> str:
    """
    Resolve `requested` to a backend that is actually installed.

    Honours the request when its dependency is importable; otherwise falls back
    to the other backend (in either direction). If neither is importable the
    request is returned unchanged so the real ImportError surfaces with its
    actionable message.
    """
    requested = requested.lower()
    if _is_importable(requested):
        return requested
    other = "sentence-transformers" if requested in _FASTEMBED else "fastembed"
    if _is_importable(other):
        logger.warning(f"'{requested}' backend unavailable; using '{other}'.")
        return other
    return requested


def _backend_and_model() -> Tuple[str, str]:
    """Resolve the active (backend, model) from settings → config defaults,
    coercing the backend to one that is actually installed."""
    s = config.get_settings()
    backend = str(s.get("embedding_backend", config.EMBEDDING_BACKEND)).lower()
    model = str(s.get("embedding_model", config.EMBEDDING_MODEL))
    return _effective_backend(backend), model


def signature() -> str:
    """
    Stable identifier of the active embedding backend+model. Written alongside an
    index so a later load can detect that the embeddings changed underneath it.
    Reflects the *effective* backend, so the stamp matches the vectors produced.
    """
    backend, model = _backend_and_model()
    return f"{backend}:{model}"


def _fastembed_name(model: str) -> str:
    """
    Map our short model ids to the fully-qualified names fastembed expects.

    The English MiniLM and the multilingual MiniLM/mpnet models live under the
    `sentence-transformers/` namespace in fastembed's catalog; the e5 model is
    already fully-qualified (`intfloat/...`) so it passes straight through.
    """
    mapping = {
        "all-MiniLM-L6-v2": "sentence-transformers/all-MiniLM-L6-v2",
        "paraphrase-multilingual-MiniLM-L12-v2":
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "paraphrase-multilingual-mpnet-base-v2":
            "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
    }
    return mapping.get(model, model)


class _E5PrefixEmbeddings:
    """
    Thin wrapper that prepends the e5 instruction prefixes the model was trained
    on — `query: ` for searches and `passage: ` for indexed chunks. Without them
    e5 retrieval is noticeably worse. Wraps any LangChain Embeddings instance and
    forwards everything else unchanged, so the rest of the app is none the wiser.
    """

    def __init__(self, inner: Any):
        self._inner = inner

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._inner.embed_documents([f"passage: {t}" for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._inner.embed_query(f"query: {text}")


def get_embeddings() -> Any:
    """
    Build the active embeddings object (a LangChain Embeddings instance).

    The backend is already resolved to one that is installed (see
    `_effective_backend`), so this never hard-fails on a missing *optional*
    dependency — the Lite build (fastembed, no torch) works on a clean install
    even though the default setting names sentence-transformers.
    """
    backend, model = _backend_and_model()

    if backend in _FASTEMBED:
        from langchain_community.embeddings import FastEmbedEmbeddings
        emb: Any = FastEmbedEmbeddings(model_name=_fastembed_name(model))
    else:
        from langchain_huggingface import HuggingFaceEmbeddings
        emb = HuggingFaceEmbeddings(model_name=model)

    # e5 models need query:/passage: prefixes for good retrieval.
    if model in getattr(config, "E5_PREFIX_MODELS", set()):
        return _E5PrefixEmbeddings(emb)
    return emb
