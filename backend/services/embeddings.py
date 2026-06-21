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

from functools import lru_cache
from typing import Any, Tuple

import config

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
        print(f"[embeddings] '{requested}' backend unavailable; using '{other}'.")
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
    """Map our short model names to the fully-qualified names fastembed expects."""
    mapping = {"all-MiniLM-L6-v2": "sentence-transformers/all-MiniLM-L6-v2"}
    return mapping.get(model, model)


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
        return FastEmbedEmbeddings(model_name=_fastembed_name(model))

    from langchain_huggingface import HuggingFaceEmbeddings
    return HuggingFaceEmbeddings(model_name=model)
