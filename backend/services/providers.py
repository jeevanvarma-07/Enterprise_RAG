"""
LLM provider factory — the single place that turns a (provider, model) pair
into a ready-to-use LangChain chat model.

Why this exists
---------------
The RAG pipeline shouldn't care *where* an LLM lives. It asks this module for
a chat model and gets back something with the standard LangChain interface
(`.invoke(...)`, `.with_structured_output(...)`). Adding a new free provider is
then just a new entry in `config.PROVIDERS` — no pipeline changes.

Provider types (see config.PROVIDERS):
  - "groq"     → langchain_groq.ChatGroq (kept; already proven in this app)
  - "openai"   → langchain_openai.ChatOpenAI pointed at the provider's base_url
                 (covers DeepSeek, Mistral, Kimi, z.ai, Gemini, OpenRouter, …)
  - "ollama"   → ChatOpenAI against a local Ollama server (offline, no key)
  - "llamacpp" → bundled GGUF via langchain-community + llama-cpp-python (offline)

Lite-path note: importing this module is cheap. Heavy local backends
(llama-cpp-python) are imported lazily, only when actually selected, so the
8 GB / no-GPU default never pays for them.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, List, Optional

import config


# ─────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────
def build_chat_model(
    provider: Optional[str],
    model: str,
    *,
    temperature: float = 0.3,
    max_tokens: int = 2048,
):
    """
    Return a LangChain chat model for (provider, model).

    If `provider` is None it is resolved from the model id via the registry.
    Raises ValueError with a clear, user-facing message when a remote
    provider has no API key configured.
    """
    if not provider:
        provider = config.provider_for_model(model)

    cfg = config.get_provider(provider)  # KeyError → unknown provider
    ptype = cfg["type"]

    if ptype == "groq":
        return _build_groq(provider, model, temperature, max_tokens)
    if ptype == "openai":
        return _build_openai_compatible(provider, model, cfg, temperature, max_tokens)
    if ptype == "ollama":
        return _build_ollama(model, cfg, temperature, max_tokens)
    if ptype == "llamacpp":
        return _build_llamacpp(model, temperature, max_tokens)

    raise ValueError(f"Unknown provider type '{ptype}' for provider '{provider}'.")


# ─────────────────────────────────────────────────────────────────────
# Per-type builders
# ─────────────────────────────────────────────────────────────────────
def _build_groq(provider: str, model: str, temperature: float, max_tokens: int):
    """Groq via its dedicated client (kept for stability)."""
    from langchain_groq import ChatGroq

    api_key = config.provider_api_key(provider)
    if not api_key:
        raise ValueError(
            "No Groq API key configured. Add one in Settings → LLM Providers "
            "(get a free key at https://console.groq.com/keys)."
        )
    return ChatGroq(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        max_retries=2,
        api_key=api_key,
    )


def _build_openai_compatible(
    provider: str, model: str, cfg: dict, temperature: float, max_tokens: int
):
    """Any OpenAI-compatible remote provider (DeepSeek, Mistral, Kimi, z.ai, Gemini…)."""
    from langchain_openai import ChatOpenAI

    api_key = config.provider_api_key(provider)
    if not api_key:
        label = cfg.get("label", provider)
        raise ValueError(
            f"No API key configured for {label}. Add one in Settings → LLM Providers."
        )
    base_url = cfg.get("base_url")
    if not base_url:
        raise ValueError(
            f"No base_url configured for '{provider}'. "
            f"Set {provider.upper()}_BASE_URL in backend/.env."
        )
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        max_retries=2,
        api_key=api_key,
        base_url=base_url,
    )


def _build_ollama(model: str, cfg: dict, temperature: float, max_tokens: int):
    """
    Local Ollama via its OpenAI-compatible endpoint. No API key needed; the
    openai client still requires a non-empty key string, so we pass a dummy.
    """
    from langchain_openai import ChatOpenAI

    base_url = cfg.get("base_url") or "http://localhost:11434/v1"
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key="ollama",          # dummy; Ollama ignores it
        base_url=base_url,
    )


def _build_llamacpp(model: str, temperature: float, max_tokens: int):
    """
    Fully offline, in-process inference via llama-cpp-python.

    Heavy + native, so it is OPT-IN (Power mode) and imported lazily. `model`
    is expected to be a GGUF filename inside config.MODELS_DIR. The actual
    bundling/auto-download lands with desktop packaging (Phase 4); this builder
    makes the wiring work today for anyone who drops a .gguf in models/.
    """
    try:
        from langchain_community.chat_models import ChatLlamaCpp
    except Exception as exc:  # pragma: no cover - optional dependency
        raise ValueError(
            "Offline model support needs 'llama-cpp-python'. It's optional and "
            "not installed by default (it's a large, native build). Install it "
            "to enable fully-offline mode, or use Ollama / a cloud provider."
        ) from exc

    model_path = config.MODELS_DIR / model
    if not model_path.exists():
        raise ValueError(
            f"Offline model '{model}' not found in {config.MODELS_DIR}. "
            "Download a GGUF model file there first."
        )
    return ChatLlamaCpp(
        model_path=str(model_path),
        temperature=temperature,
        max_tokens=max_tokens,
        n_ctx=4096,
        verbose=False,
    )


# ─────────────────────────────────────────────────────────────────────
# Fallback ordering
# ─────────────────────────────────────────────────────────────────────
def fallback_candidates(provider: Optional[str], model: str) -> List[tuple]:
    """
    Ordered (provider, model) pairs to attempt for one chat request.

    The requested pair comes first; then every OTHER currently-configured
    provider's first registered model, in registry order, as fallback targets.
    Providers with no static model id (a fresh Ollama / llama.cpp before any
    model exists) are skipped here — they're reached via their own detection
    path, not blind fallback.

    Pure and side-effect-free (no network), so the generation layer gets a
    deterministic order and this is trivial to unit-test.
    """
    primary_provider = provider or config.provider_for_model(model)
    candidates: List[tuple] = [(primary_provider, model)]
    seen = {primary_provider}
    for name, cfg in config.PROVIDERS.items():
        if name in seen:
            continue
        if not config.provider_is_configured(name):
            continue
        models = cfg.get("models") or []
        if not models:
            continue
        candidates.append((name, models[0]["id"]))
        seen.add(name)
    return candidates


# ─────────────────────────────────────────────────────────────────────
# Ollama auto-detection  (so users with Ollama get offline models for free)
# ─────────────────────────────────────────────────────────────────────
def detect_ollama(timeout: float = 0.5) -> dict[str, Any]:
    """
    Probe the local Ollama server and list its installed models.

    Returns {"running": bool, "models": [{"id","label"}], "base_url": str}.
    Uses a short timeout and never raises, so it's safe to call on every
    /api/providers request even when Ollama isn't installed.
    """
    cfg = config.get_provider("ollama")
    base_url = cfg.get("base_url") or "http://localhost:11434/v1"
    models: List[dict] = []
    try:
        # /v1/models is the OpenAI-compatible listing endpoint Ollama serves.
        req = urllib.request.Request(base_url.rstrip("/") + "/models")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        for m in data.get("data", []):
            mid = m.get("id")
            if mid:
                models.append({"id": mid, "label": mid})
        return {"running": True, "models": models, "base_url": base_url}
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return {"running": False, "models": [], "base_url": base_url}
