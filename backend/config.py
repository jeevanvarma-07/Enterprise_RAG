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
    "deepseek": {
        "label": "DeepSeek",
        "type": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
        "models": [
            {"id": "deepseek-chat", "label": "DeepSeek Chat"},
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

DEFAULT_PROVIDER: str = "groq"
DEFAULT_MODEL: str = "llama-3.1-8b-instant"


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
    },
    "balanced": {
        "label": "Balanced",
        "description": "Mid-range machine. Adds cross-encoder reranking and OCR "
                       "for scanned files, with moderate ingest concurrency.",
        "rerank": True,
        "ocr": True,
        "upload_concurrency": 6,
        "embedding": "fastembed",
    },
    "power": {
        "label": "Power",
        "description": "16 GB + GPU. Highest-quality embeddings, reranking, OCR, "
                       "and high ingest concurrency.",
        "rerank": True,
        "ocr": True,
        "upload_concurrency": 12,
        "embedding": "sentence-transformers",
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
    "active_provider": "groq",
    "active_model": DEFAULT_MODEL,
    "embedding_backend": EMBEDDING_BACKEND,  # sentence-transformers | fastembed
    "embedding_model": EMBEDDING_MODEL,
    "rerank": "auto",               # auto | on | off  (auto = follow profile)
    "ocr": "auto",                  # auto | on | off  (auto = follow profile; off on Lite)
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
