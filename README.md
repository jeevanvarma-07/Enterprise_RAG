# Enterprise RAG

A **local-first, cross-platform desktop app** for Retrieval-Augmented Generation.
Upload your own documents (PDF, Excel/CSV, images, TXT, URLs), index them locally, and
chat with them — answers are grounded **only** in your content, with source citations.
Your documents never leave your machine.

> Originally a web app (4th-sem B.Sc. AI & DS project), now a professional desktop app
> with offline LLM support, multiple LLM providers, hybrid search, reranking, and
> performance modes — built entirely with **free / open-source** tools.

---

## ✨ Features

- **Local-first & private** — documents, index, and chat history live in a per-user data
  dir on your machine; nothing is uploaded to a third party (except your chosen LLM call).
- **Multi-format ingestion** — PDF, Excel/CSV, TXT, images (optional OCR), and URLs.
- **Advanced RAG** — history-aware query rewriting → multi-query expansion → **hybrid
  search** (dense FAISS + BM25 keyword) → Reciprocal Rank Fusion → optional cross-encoder
  **reranking** → grounded, cited Markdown answers. Streamed token-by-token (SSE).
- **Multiple LLM providers** — Groq, plus any OpenAI-compatible free API (NVIDIA NIM,
  Mistral, Kimi/Moonshot, z.ai, OpenRouter…), Google Gemini, **local Ollama** (auto-detected),
  and **fully offline** `llama.cpp` (GGUF) for no-internet use.
- **Encrypted in-app API keys** — paste keys in Settings; they're **Fernet-encrypted at
  rest**, never stored in the repo or a plaintext file.
- **Performance modes** — Lite / Balanced / Power profiles, auto-suggested from detected
  hardware (RAM / CPU / GPU). The default Lite path runs smoothly on an 8 GB, no-GPU machine.
- **Torch-free option** — ONNX embeddings (`fastembed`) for a lean install; switch to the
  PyTorch backend for max accuracy and rebuild the index in one click.
- **Chat persistence** — sessions + history in SQLite, with a sidebar to revisit them.
- **Evaluation & telemetry** — an **Evaluation** tab with the four RAGAS-style quality
  metrics (faithfulness, answer relevancy, context precision, context recall), computed
  Lite-safe from the configured LLM-judge + local embeddings (no heavy `ragas` dependency).
  Run a single question live or a labelled dataset, alongside per-request token/latency
  telemetry and an opt-in **Retrieval Inspector** that traces every pipeline stage.
- **Vector store management** — view, selectively delete, or export the FAISS index.
- **Guided onboarding** — a first-run wizard (detect hardware → pick a mode → add a key) plus an
  always-available in-app Help & About panel.

---

## 🏗️ Architecture

```
┌──────────────────── Enterprise RAG (desktop) ─────────────────────┐
│  Tauri 2 shell (Rust)                                             │
│   • picks a free port, sets a per-user data dir                   │
│   • spawns the backend sidecar, waits for /api/health            │
│   • opens the WebView, injecting the API base URL                │
│                                                                   │
│   WebView (React build)  ──HTTP──▶  rag-backend (PyInstaller)     │
│   frontend/dist                     FastAPI + FAISS + embeddings  │
└───────────────────────────────────────────────────────────────────┘
```

```
frontend/                 React 19 + Vite + TypeScript + Tailwind v4 + Framer Motion
  src-tauri/              Tauri 2 desktop shell (Rust) + PyInstaller sidecar wiring
backend/
  main.py                 FastAPI app — all REST endpoints, CORS, upload orchestration
  config.py               typed settings, provider registry, performance profiles
  services/
    document_processing.py PDF/Excel/CSV/image/txt extraction + chunking
    indexing.py            VectorStoreManager — FAISS + metadata
    generation.py          RAGPipeline — multi-query + hybrid + RRF + rerank + LLM
    providers.py           multi-provider LLM layer (cloud / Ollama / llama.cpp)
    embeddings.py          pluggable embeddings (sentence-transformers | fastembed/ONNX)
    keystore.py            Fernet-encrypted API-key store
    storage.py             SQLite chat sessions + history
    system_info.py         hardware detection → suggested performance mode
```

---

## 🚀 Run from source (development)

**Backend** (Python 3.9–3.11):
```bash
cd backend
python -m venv venv
venv/Scripts/activate          # Windows (bash);  Linux/macOS: source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev                     # http://localhost:5173
```

API keys: set them in-app (Settings → LLM Providers), or for dev put them in `backend/.env`
(e.g. `GROQ_API_KEY=...`). `.env` is gitignored — never commit a key.

One-click on Windows: `START_PROJECT.bat`.

---

## 📦 Build the desktop app

Requires Rust (`rustup`) on the build machine; everything else ships inside the app.

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File scripts/build-desktop.ps1
# Linux / macOS / Git-Bash
scripts/build-desktop.sh
```

This freezes the backend with PyInstaller, stages it as a Tauri sidecar, and builds the
installers into `frontend/src-tauri/target/release/bundle/` (Windows `.exe`/`.msi`;
Linux `.AppImage`/`.deb`). See [`PHASE4_PACKAGING.md`](PHASE4_PACKAGING.md) for details and
the Lite vs Full build flavours.

---

## 🧠 RAG pipeline

```
User query
  └─ history-aware rewrite (make follow-ups standalone)
       └─ multi-query: LLM generates query variations
            └─ each variation → hybrid retrieval (dense MMR + BM25), fused via RRF
                 └─ optional cross-encoder reranking (Balanced/Power)
                      └─ (+ exact CSV/Excel numeric-ID lookup prepended to context)
                           └─ chosen LLM → streamed Markdown answer + sources
```

---

## 🛠️ Tech stack

| Layer | Technology |
|-------|-----------|
| Desktop shell | Tauri 2 (Rust) + WebView; PyInstaller-frozen backend sidecar |
| Frontend | React 19, Vite, TypeScript, Tailwind v4, Framer Motion |
| Backend | FastAPI, Uvicorn, Python 3.9+ |
| Embeddings | `all-MiniLM-L6-v2` via sentence-transformers **or** fastembed (ONNX, torch-free) |
| Vector store | FAISS (CPU) + BM25 (`rank_bm25`) hybrid |
| Reranking | `flashrank` cross-encoder (optional, ONNX) |
| LLM | Groq · OpenAI-compatible providers · Gemini · Ollama · local `llama.cpp` |
| State | SQLite (chat history) + JSON settings; Fernet-encrypted keys |
| Doc parsing | PyPDF2, pandas, openpyxl, Pillow, optional Tesseract/EasyOCR |

---

## 📁 Data location

User content lives in the per-user app-data dir (never in the repo or Program Files):

| OS | Path |
|----|------|
| Windows | `%APPDATA%\com.jeevanvarma.enterpriserag\data` |
| Linux | `~/.local/share/com.jeevanvarma.enterpriserag/data` |

It holds `uploads/`, `vector_store/`, `settings.json`, `rag.db`, encrypted keys, and
downloaded models.

---

## 🧪 Tests

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest
```

---

*Author: Jeevan Varma R. Built primarily with AI coding assistants. See
[`CLAUDE.md`](CLAUDE.md) and [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) for the
project guide and roadmap.*
