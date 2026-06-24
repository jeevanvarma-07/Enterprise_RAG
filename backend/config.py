"""
Central configuration for the Enterprise RAG backend.

Everything that used to be a hardcoded string ("uploads", "vector_store",
"http://localhost:5173", the model dropdown list) now lives here so the same
codebase runs identically as a dev web app and as a packaged desktop app.

Key ideas
---------
- **Paths** resolve from a single DATA_DIR. In dev it defaults to the backend
  folder (so existing uploads/ and vector_store/ keep working unchanged). The
  packaged app sets RAG_DATA_DIR to a per-user app-data directory.
- **Settings** (non-secret preferences: active model, mode, etc.) persist to a
  JSON file and merge over defaults. API keys are NOT stored here yet — they
  still come from the environment / .env (Phase 1 adds an encrypted key store).
- **Models** are described in one registry, grouped by provider, so the
  frontend dropdown and the future provider layer share one source of truth.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

# Single source of truth for the app version (FastAPI metadata, /api/health,
# and the desktop shell's about screen all read this).
APP_VERSION: str = "2.0.0"

# ─────────────────────────────────────────────────────────────────────
# Paths  (cross-platform, no hardcoded C:\ or cwd assumptions)
# ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent  # the backend/ folder


def _default_data_dir() -> Path:
    """
    Where uploads, the vector store, and settings.json live.

    - If RAG_DATA_DIR is set (the packaged app does this), use it.
    - Otherwise default to the backend folder, so existing dev data
      (backend/uploads, backend/vector_store) keeps working as-is.
    """
    env_dir = os.getenv("RAG_DATA_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    return BASE_DIR


DATA_DIR: Path = _default_data_dir()
UPLOADS_DIR: Path = DATA_DIR / "uploads"
VECTOR_STORE_DIR: Path = DATA_DIR / "vector_store"
MODELS_DIR: Path = DATA_DIR / "models"          # for downloaded local GGUF models (Phase 1)
SETTINGS_PATH: Path = DATA_DIR / "settings.json"
METADATA_PATH: Path = VECTOR_STORE_DIR / "metadata.json"
DB_PATH: Path = DATA_DIR / "rag.db"          # SQLite: chat sessions + history


def ensure_dirs() -> None:
    """Create the data directories if they don't exist yet."""
    for d in (DATA_DIR, UPLOADS_DIR, VECTOR_STORE_DIR, MODELS_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────
# Server / network
# ─────────────────────────────────────────────────────────────────────
HOST: str = os.getenv("RAG_HOST", "127.0.0.1")
PORT: int = int(os.getenv("RAG_PORT", "8000"))

# CORS origins. Dev uses the Vite ports; the packaged Tauri app sets
# RAG_CORS_ORIGINS (comma-separated) to its own origin.
_default_origins = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:3000",
    "tauri://localhost",
    "http://tauri.localhost",
]
CORS_ORIGINS: list[str] = [
    o.strip()
    for o in os.getenv("RAG_CORS_ORIGINS", ",".join(_default_origins)).split(",")
    if o.strip()
]


# ─────────────────────────────────────────────────────────────────────
# Provider registry  (single source of truth for the dropdown + provider layer)
#
# Most free LLM APIs are OpenAI-compatible, so they share one client and only
# differ by base_url + which env var holds the key. Groq keeps its dedicated
# langchain-groq client (already battle-tested). "ollama" and "llamacpp" need
# no API key — they run locally (offline support).
#
# Every base_url can be overridden per-provider with <PROVIDER>_BASE_URL, and
# every key is read from <api_key_env>. Nothing here is a secret.
#
# type:  "groq"     -> langchain_groq.ChatGroq
#        "openai"   -> langchain_openai.ChatOpenAI (base_url + key)
#        "ollama"   -> ChatOpenAI against a local Ollama server (no key)
#        "llamacpp" -> bundled offline GGUF via llama-cpp-python (no key)
#
# Note: deprecated Groq models (e.g. mixtral-8x7b-32768) intentionally removed.
# ─────────────────────────────────────────────────────────────────────
PROVIDERS: dict[str, dict[str, Any]] = {
    "groq": {
        "label": "Groq",
        "type": "groq",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
        "models": [
            {"id": "llama-3.1-8b-instant", "label": "Llama 3.1 8B (fast)"},
            {"id": "llama-3.3-70b-versatile", "label": "Llama 3.3 70B (quality)"},
        ],
    },
    "google": {
        "label": "Google Gemini",
        "type": "openai",  # Gemini exposes an OpenAI-compatible endpoint
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key_env": "GOOGLE_API_KEY",
        "models": [
            {"id": "gemini-2.0-flash", "label": "Gemini 2.0 Flash"},
            {"id": "gemini-1.5-flash", "label": "Gemini 1.5 Flash"},
        ],
    },
    "nvidia": {
        # NVIDIA NIM (build.nvidia.com) — genuinely free, OpenAI-compatible.
        # Sign up for the NVIDIA Developer Program, generate an "nvapi-…" key,
        # and call the same /v1/chat/completions endpoint. 1k inference credits
        # on signup (5k on request), 40 req/min, no card, no GPU required.
        # Replaces DeepSeek's direct API, which has no free tier (402 / no
        # balance) — NVIDIA hosts Llama/Qwen/DeepSeek/etc. for free instead.
        "label": "NVIDIA NIM",
        "type": "openai",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "api_key_env": "NVIDIA_API_KEY",
        "models": [
            {"id": "meta/llama-3.1-8b-instruct", "label": "Llama 3.1 8B (fast)"},
            {"id": "meta/llama-3.3-70b-instruct", "label": "Llama 3.3 70B (quality)"},
        ],
    },
    "mistral": {
        "label": "Mistral",
        "type": "openai",
        "base_url": "https://api.mistral.ai/v1",
        "api_key_env": "MISTRAL_API_KEY",
        "models": [
            {"id": "mistral-small-latest", "label": "Mistral Small"},
            {"id": "open-mistral-nemo", "label": "Mistral Nemo"},
        ],
    },
    "moonshot": {
        "label": "Kimi (Moonshot)",
        "type": "openai",
        "base_url": "https://api.moonshot.ai/v1",
        "api_key_env": "MOONSHOT_API_KEY",
        "models": [
            {"id": "moonshot-v1-8k", "label": "Kimi 8k"},
            {"id": "moonshot-v1-32k", "label": "Kimi 32k"},
        ],
    },
    "zai": {
        "label": "z.ai (GLM)",
        "type": "openai",
        "base_url": "https://api.z.ai/api/paas/v4",
        "api_key_env": "ZAI_API_KEY",
        "models": [
            {"id": "glm-4-flash", "label": "GLM-4 Flash"},
        ],
    },
    "cerebras": {
        # Wafer-scale inference — very fast, 1M tokens/day free tier. A strong
        # backup for the laptop demo: far roomier than Groq's 6k/min, so the
        # "Request too large" 413 is much less likely.
        #
        # NOTE: Cerebras's free tier rotated its catalogue off the Llama models —
        # current free accounts get GPT-OSS 120B and GLM-4.7 (both *reasoning*
        # models: they spend tokens "thinking" before the answer, which the
        # 2048-token default in providers.build_chat_model comfortably covers).
        # The exact list is per-account; verify with `GET /v1/models` (it needs a
        # browser User-Agent — the API sits behind Cloudflare, which 1010-blocks
        # the default Python UA, though langchain's httpx client gets through).
        "label": "Cerebras",
        "type": "openai",
        "base_url": "https://api.cerebras.ai/v1",
        "api_key_env": "CEREBRAS_API_KEY",
        "models": [
            {"id": "gpt-oss-120b", "label": "GPT-OSS 120B (quality)"},
            {"id": "zai-glm-4.7", "label": "GLM 4.7 (reasoning)"},
        ],
    },
    "openrouter": {
        # Aggregator: many models behind one key, including several free ones
        # (the ":free" suffix). Handy fallback that doesn't burn a single
        # provider's quota.
        "label": "OpenRouter",
        "type": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "models": [
            {"id": "meta-llama/llama-3.3-70b-instruct:free", "label": "Llama 3.3 70B (free)"},
            {"id": "deepseek/deepseek-chat-v3-0324:free", "label": "DeepSeek V3 (free)"},
        ],
    },
    "opencode": {
        "label": "OpenCode Zen",
        "type": "openai",
        "base_url": "https://opencode.ai/zen/v1",
        "api_key_env": "OPENCODE_API_KEY",
        "models": [
            {"id": "grok-code", "label": "Grok Code"},
        ],
    },
    # ── Offline / local (no API key, no internet) ───────────────────────
    "ollama": {
        "label": "Ollama (local, auto-detected)",
        "type": "ollama",
        # Ollama's OpenAI-compatible endpoint. Overridable with OLLAMA_BASE_URL.
        "base_url": "http://localhost:11434/v1",
        "api_key_env": None,           # not needed for local
        "models": [],                  # discovered live at runtime (see providers.py)
    },
    "llamacpp": {
        "label": "Offline (built-in model)",
        "type": "llamacpp",
        "base_url": None,
        "api_key_env": None,           # not needed — runs in-process
        "models": [],                  # populated once a GGUF is downloaded (Phase 1/4)
    },
}

# Default provider/model. Cerebras GPT-OSS 120B is the default because its free
# tier is far roomier than Groq's 6k tokens/min (which throws 413 "Request too
# large" on this pipeline's multi-call prompts). On a machine with no Cerebras
# key the picker still shows this as the default but marks it unavailable, and
# `llm_fallback` retries another configured provider — same behaviour Groq had.
DEFAULT_PROVIDER: str = "cerebras"
DEFAULT_MODEL: str = "gpt-oss-120b"


# ─────────────────────────────────────────────────────────────────────
# Reranking  (Power-gated, optional — needs the `flashrank` package)
#
# A cross-encoder re-scores the fused candidate chunks against the query for
# sharper relevance than dense+BM25 fusion alone. It costs CPU/RAM, so it's
# OFF by default (Lite path) and only kicks in for balanced/power modes — see
# rerank_enabled(). The model is a tiny ONNX cross-encoder downloaded once into
# MODELS_DIR; if flashrank isn't installed, retrieval silently falls back to
# the unranked fusion order (never breaks chat).
# ─────────────────────────────────────────────────────────────────────
# Embeddings backend. Default stays sentence-transformers so existing FAISS
# indexes (built with it) keep working unchanged. "fastembed" is an optional
# ONNX backend that drops the heavy torch dep for the Lite profile — switching
# it invalidates an existing index (different vectors), so it's opt-in.
EMBEDDING_BACKEND: str = os.getenv("RAG_EMBEDDING_BACKEND", "sentence-transformers")
EMBEDDING_MODEL: str = os.getenv("RAG_EMBEDDING_MODEL", "all-MiniLM-L6-v2")


# ─────────────────────────────────────────────────────────────────────
# Embedding model registry  (single source of truth for the picker + provider)
#
# The default `all-MiniLM-L6-v2` is English-only, so Tamil / other non-English
# documents retrieve poorly. These multilingual models fix that WITHOUT touching
# the Lite-first rule: every one is available through `fastembed` (ONNX, no
# torch), so the 8 GB / no-GPU laptop can run them. They differ in vector size
# and weight, so picking a heavier one is a quality/RAM trade-off the user makes
# per machine (the smallest is the Lite default; the 3060 desktop can opt up).
#
# IMPORTANT: switching the model invalidates an existing index (vectors from
# different models aren't comparable) — the user must hit "Rebuild index". That
# migration path already exists (`VectorStoreManager.rebuild_embeddings`), and
# the `embedding_info.json` signature stamp warns on a mismatch. So nothing here
# auto-switches; it only widens the menu of selectable models.
#
# `model` is our short id (stored in settings + the index signature). `fastembed`
# names map to the fully-qualified ids in services/embeddings._fastembed_name().
# ─────────────────────────────────────────────────────────────────────
EMBEDDING_MODELS: list[dict[str, Any]] = [
    {
        "id": "all-MiniLM-L6-v2",
        "label": "English (MiniLM-L6)",
        "languages": "English",
        "dim": 384,
        "size_gb": 0.09,
        "multilingual": False,
        "tier": "lite",
        "note": "Smallest & fastest. English-only — the original default.",
    },
    {
        "id": "paraphrase-multilingual-MiniLM-L12-v2",
        "label": "Multilingual (MiniLM-L12)",
        "languages": "50+ languages incl. Tamil",
        "dim": 384,
        "size_gb": 0.22,
        "multilingual": True,
        "tier": "lite",
        "note": "Recommended. Same 384-dim size class as English MiniLM, "
                "covers Tamil + 50 languages. Best fit for the 8 GB laptop.",
    },
    {
        "id": "paraphrase-multilingual-mpnet-base-v2",
        "label": "Multilingual HQ (mpnet)",
        "languages": "50+ languages incl. Tamil",
        "dim": 768,
        "size_gb": 1.0,
        "multilingual": True,
        "tier": "balanced",
        "note": "Higher-quality multilingual retrieval. 768-dim — more RAM/CPU "
                "than MiniLM; good on the desktop or a roomy machine.",
    },
    {
        "id": "intfloat/multilingual-e5-large",
        "label": "Multilingual Max (e5-large)",
        "languages": "100+ languages incl. Tamil",
        "dim": 1024,
        "size_gb": 2.24,
        "multilingual": True,
        "tier": "power",
        "note": "Best quality, 1024-dim, ~2.2 GB. Power machines only "
                "(RTX 3060 / 16 GB) — too heavy for the Lite laptop.",
    },
]

# Models that need an e5-style "query:"/"passage:" prefix to embed well. The
# embeddings backend prepends these automatically (see services/embeddings.py).
E5_PREFIX_MODELS: set[str] = {"intfloat/multilingual-e5-large"}


def list_embedding_models() -> list[dict[str, Any]]:
    """
    The selectable embedding models for the Settings picker, each tagged with
    whether it is the one currently active. The UI shares this single registry
    (via GET /api/embeddings/models) so the menu and the backend never drift.
    """
    active = str(get_settings().get("embedding_model", EMBEDDING_MODEL))
    return [{**m, "active": m["id"] == active} for m in EMBEDDING_MODELS]

RERANK_MODEL: str = os.getenv("RAG_RERANK_MODEL", "ms-marco-MiniLM-L-12-v2")
RERANK_CANDIDATES: int = int(os.getenv("RAG_RERANK_CANDIDATES", "12"))  # fused chunks fed to the reranker
RERANK_TOP_N: int = int(os.getenv("RAG_RERANK_TOP_N", "6"))             # chunks kept after reranking


# ─────────────────────────────────────────────────────────────────────
# Performance profiles  (Phase 3 — Lite / Balanced / Power)
#
# One `mode` setting scales the app from the i3/8 GB lab PC to the 16 GB + GPU
# desktop. Each profile is a bundle of cost/quality defaults:
#   - rerank             : run the cross-encoder reranker (CPU/RAM cost)
#   - ocr                : OCR scanned PDFs / images (heavy: Tesseract + RAM)
#   - upload_concurrency : how many files to ingest at once
#   - embedding          : the *suggested* embedding backend for this profile
#                          (advisory only — we never auto-switch it, because
#                          changing backend invalidates an existing index and
#                          needs a deliberate rebuild)
# The per-feature `rerank` / `ocr` settings can still override the profile via
# their "auto|on|off" switches (auto = follow the profile).
# ─────────────────────────────────────────────────────────────────────
MODE_PROFILES: dict[str, dict[str, Any]] = {
    "lite": {
        "label": "Lite",
        "description": "8 GB RAM, no GPU. Cloud LLM + ONNX embeddings; reranking "
                       "and OCR off. Fastest start, lowest memory.",
        "rerank": False,
        "ocr": False,
        "upload_concurrency": 3,
        "embedding": "fastembed",
        # Suggested (advisory) embedding model + table engine for this profile.
        # Never auto-applied — see EMBEDDING_MODELS / table_engine() notes.
        "embedding_model": "paraphrase-multilingual-MiniLM-L12-v2",
        "table_engine": "pdfplumber",
    },
    "balanced": {
        "label": "Balanced",
        "description": "Mid-range machine. Adds cross-encoder reranking and OCR "
                       "for scanned files, with moderate ingest concurrency.",
        "rerank": True,
        "ocr": True,
        "upload_concurrency": 6,
        "embedding": "fastembed",
        "embedding_model": "paraphrase-multilingual-MiniLM-L12-v2",
        "table_engine": "pdfplumber",
    },
    "power": {
        "label": "Power",
        "description": "16 GB + GPU. Highest-quality embeddings, reranking, OCR, "
                       "and high ingest concurrency.",
        "rerank": True,
        "ocr": True,
        "upload_concurrency": 12,
        "embedding": "sentence-transformers",
        "embedding_model": "paraphrase-multilingual-mpnet-base-v2",
        "table_engine": "docling",
    },
}

DEFAULT_MODE: str = "lite"


def active_mode() -> str:
    """The current performance profile name, validated against MODE_PROFILES."""
    m = str(get_settings().get("mode", DEFAULT_MODE)).lower()
    return m if m in MODE_PROFILES else DEFAULT_MODE


def ocr_enabled() -> bool:
    """
    Whether to run OCR on scanned PDFs / images. Honors an explicit on/off in
    the `ocr` setting; "auto" (default) follows the active profile — off on Lite
    so the 8 GB no-GPU machine never spends RAM/CPU on Tesseract.
    """
    s = get_settings()
    pref = str(s.get("ocr", "auto")).lower()
    if pref in ("on", "true", "1", "yes"):
        return True
    if pref in ("off", "false", "0", "no"):
        return False
    return MODE_PROFILES[active_mode()]["ocr"]


def upload_concurrency() -> int:
    """How many files to ingest concurrently under the active profile."""
    return int(MODE_PROFILES[active_mode()]["upload_concurrency"])


def table_engine() -> str:
    """
    Which engine extracts structured tables from PDFs.

    Returns one of: "pdfplumber" (pure-Python, no torch, Lite-safe — the
    default), "docling" (high-quality but needs Python ≥3.10 + torch, so it's a
    Power-mode opt-in), or "off" (no dedicated table extraction).

    The `table_engine` setting honors an explicit choice; "auto" (default)
    follows the active profile — pdfplumber on Lite/Balanced, docling on Power.
    Availability is checked at call time in services/table_extraction.py, which
    silently falls back to pdfplumber → plain text if the chosen engine isn't
    installed, so the laptop and the 3.9 CI never break.
    """
    pref = str(get_settings().get("table_engine", "auto")).lower()
    if pref in ("off", "none", "false", "0", "no"):
        return "off"
    if pref in ("pdfplumber", "docling"):
        return pref
    return str(MODE_PROFILES[active_mode()].get("table_engine", "pdfplumber"))


def get_provider(name: str) -> dict[str, Any]:
    """
    Return a provider's config with its base_url overridden by
    <PROVIDER>_BASE_URL if that env var is set. Raises KeyError if unknown.
    """
    cfg = dict(PROVIDERS[name])
    override = os.getenv(f"{name.upper()}_BASE_URL")
    if override:
        cfg["base_url"] = override.rstrip("/")
    return cfg


def provider_api_key(name: str) -> str:
    """
    Return the configured API key for a provider, or '' if none/needed.

    Resolution order: the in-app **encrypted key store** (keys pasted in
    Settings) wins, then the environment / `.env` fallback. This lets the
    packaged app keep keys out of any plaintext file while staying compatible
    with the dev workflow of putting keys in `backend/.env`.
    """
    cfg = PROVIDERS.get(name, {})
    env_name = cfg.get("api_key_env")
    if not env_name:
        return ""
    # In-app encrypted store first (imported lazily to avoid a hard dependency
    # and any import cycle at module load).
    try:
        from services import keystore
        stored = keystore.get_key(name)
        if stored:
            return stored
    except Exception:
        pass
    return os.getenv(env_name, "")


def provider_is_configured(name: str) -> bool:
    """
    True when a provider is usable: local types need no key; remote types
    need their key present. (Ollama reachability is probed separately.)
    """
    cfg = PROVIDERS.get(name)
    if not cfg:
        return False
    if cfg["type"] in ("ollama", "llamacpp"):
        return True
    return bool(provider_api_key(name))


def provider_for_model(model_id: str) -> str:
    """Find which provider owns a model id (first match). Falls back to DEFAULT_PROVIDER."""
    for name, cfg in PROVIDERS.items():
        if any(m["id"] == model_id for m in cfg["models"]):
            return name
    return DEFAULT_PROVIDER


def list_models() -> list[dict[str, Any]]:
    """
    Flat list of all known models, each tagged with its provider, the
    provider's friendly label, and whether that provider is configured.
    The frontend uses `available` to group/disable unusable options.
    """
    out: list[dict[str, Any]] = []
    for name, cfg in PROVIDERS.items():
        available = provider_is_configured(name)
        for m in cfg["models"]:
            out.append({
                "provider": name,
                "provider_label": cfg["label"],
                "available": available,
                **m,
            })
    return out


def list_providers() -> list[dict[str, Any]]:
    """Summary of every provider for the settings UI (no secrets leaked)."""
    out: list[dict[str, Any]] = []
    for name, cfg in PROVIDERS.items():
        out.append({
            "name": name,
            "label": cfg["label"],
            "type": cfg["type"],
            "configured": provider_is_configured(name),
            "needs_key": bool(cfg.get("api_key_env")),
            "model_count": len(cfg["models"]),
        })
    return out


# ─────────────────────────────────────────────────────────────────────
# Settings  (non-secret user preferences, persisted as JSON)
# ─────────────────────────────────────────────────────────────────────
DEFAULT_SETTINGS: dict[str, Any] = {
    "onboarded": False,             # has the first-run welcome wizard been completed?
    "mode": "lite",                 # lite | balanced | power  (drives Phase 3 profiles)
    "active_provider": DEFAULT_PROVIDER,
    "active_model": DEFAULT_MODEL,
    "embedding_backend": EMBEDDING_BACKEND,  # sentence-transformers | fastembed
    "embedding_model": EMBEDDING_MODEL,      # see EMBEDDING_MODELS (multilingual options)
    "rerank": "auto",               # auto | on | off  (auto = follow profile)
    "ocr": "auto",                  # auto | on | off  (auto = follow profile; off on Lite)
    "table_engine": "auto",         # auto | pdfplumber | docling | off  (see table_engine())
    "llm_fallback": True,           # auto-retry with another configured provider if the chosen LLM fails
    # Prompt-size budget — caps how big each LLM request can get, so a long chat
    # or a big index can't blow past a provider's tokens-per-minute limit (Groq's
    # free tier is only 6,000 TPM). history_turns trims the conversation re-sent
    # each turn to a sliding window; context_chars caps the retrieved text.
    "history_turns": 3,             # prior user/ai exchanges re-sent to the LLM (0 = none)
    "context_chars": 6000,          # max characters of retrieved context per request (~1.5k tokens)
    # Retrieval tuning — defaults mirror the long-standing hardcoded values, so
    # behavior is unchanged until a user deliberately tweaks them. All clamped
    # to safe ranges in retrieval_params() so a bad value can't break chat.
    "top_k": 5,                     # dense (MMR) hits kept per query variation
    "fetch_k": 20,                  # MMR candidate pool before diversity pruning
    "mmr_lambda": 0.6,              # 0 = max diversity, 1 = max relevance
    "bm25_k": 8,                    # sparse keyword hits per query (0 = dense only)
    "final_k": RERANK_TOP_N,        # chunks finally sent to the LLM
    "rerank_candidates": RERANK_CANDIDATES,  # fused chunks fed to the reranker
}


# Bounds for each tunable retrieval knob: (low, high). Keeps the cost/quality
# trade-off inside a sane envelope no matter what lands in settings.json.
_RETRIEVAL_BOUNDS: dict[str, tuple] = {
    "top_k": (1, 20),
    "fetch_k": (1, 80),
    "mmr_lambda": (0.0, 1.0),
    "bm25_k": (0, 20),
    "final_k": (1, 20),
    "rerank_candidates": (1, 50),
}

# Bounds for the prompt-size budget knobs.
_PROMPT_BOUNDS: dict[str, tuple] = {
    "history_turns": (0, 20),       # 0 = send no history; 20 = effectively unlimited
    "context_chars": (500, 60000),  # ~125 to ~15k tokens of context
}


def retrieval_params() -> dict[str, Any]:
    """
    Resolve the retrieval knobs from settings, each coerced to a number and
    clamped to its safe range. Invalid/missing values fall back to the default.
    """
    s = get_settings()

    def _num(key: str, is_float: bool) -> Any:
        lo, hi = _RETRIEVAL_BOUNDS[key]
        default = DEFAULT_SETTINGS[key]
        try:
            val = float(s.get(key, default)) if is_float else int(s.get(key, default))
        except (TypeError, ValueError):
            val = default
        return max(lo, min(hi, val))

    return {
        "top_k": _num("top_k", False),
        "fetch_k": _num("fetch_k", False),
        "mmr_lambda": _num("mmr_lambda", True),
        "bm25_k": _num("bm25_k", False),
        "final_k": _num("final_k", False),
        "rerank_candidates": _num("rerank_candidates", False),
    }


def prompt_budget() -> dict[str, int]:
    """
    Resolve the prompt-size budget from settings, clamped to safe ranges.

    Returns:
      - history_turns:    how many prior user/ai exchanges to re-send (0 = none)
      - history_messages: that figure as a raw message count (turns * 2)
      - context_chars:    max characters of retrieved context per request

    These cap each request so a long conversation or a large index can't push a
    single call past a provider's tokens-per-minute limit (the 413 "Request too
    large" error on Groq's 6,000 TPM free tier).
    """
    s = get_settings()

    def _int(key: str) -> int:
        lo, hi = _PROMPT_BOUNDS[key]
        default = DEFAULT_SETTINGS[key]
        try:
            val = int(s.get(key, default))
        except (TypeError, ValueError):
            val = default
        return max(lo, min(hi, val))

    turns = _int("history_turns")
    return {
        "history_turns": turns,
        "history_messages": turns * 2,   # each turn = one user + one ai message
        "context_chars": _int("context_chars"),
    }


def rerank_enabled() -> bool:
    """
    Whether to run cross-encoder reranking. Honors an explicit on/off in
    settings; "auto" (the default) enables it for balanced/power modes and
    leaves it off on the Lite path so the 8 GB no-GPU machine stays fast.
    """
    s = get_settings()
    pref = str(s.get("rerank", "auto")).lower()
    if pref in ("on", "true", "1", "yes"):
        return True
    if pref in ("off", "false", "0", "no"):
        return False
    return MODE_PROFILES[active_mode()]["rerank"]


def fallback_enabled() -> bool:
    """
    Whether to automatically retry with another *configured* provider when the
    chosen LLM fails (missing key, rate-limit, network / offline). On by default;
    a user with only one configured provider sees no change — there is simply
    nothing to fall back to. Disable by setting `llm_fallback` to a falsey value.
    """
    s = get_settings()
    pref = str(s.get("llm_fallback", True)).lower()
    return pref not in ("off", "false", "0", "no")


def get_settings() -> dict[str, Any]:
    """Return persisted settings merged over defaults (defaults win on missing keys)."""
    settings = dict(DEFAULT_SETTINGS)
    if SETTINGS_PATH.exists():
        try:
            settings.update(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass  # corrupt/unreadable settings → fall back to defaults
    return settings


def save_settings(new_values: dict[str, Any]) -> dict[str, Any]:
    """Merge new_values into persisted settings and write to disk. Returns the result."""
    ensure_dirs()
    current = get_settings()
    current.update(new_values)
    SETTINGS_PATH.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current
