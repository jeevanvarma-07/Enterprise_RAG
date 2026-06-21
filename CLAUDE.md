# CLAUDE.md

Guidance for AI coding agents (Claude Code, Cursor, Antigravity, etc.) working in this repo.
Read this first. Then read `IMPLEMENTATION_PLAN.md` for the roadmap.

---

## 1. What this project is

**Enterprise RAG System** — a local-first Retrieval-Augmented Generation app. Users upload
their own documents (PDF, Excel/CSV, images, txt, URLs), the app indexes them into a vector
store, and they chat with their documents. Answers are grounded *only* in uploaded content,
with source citations.

- **Origin:** 4th-semester B.Sc. (AI & Data Science) project — a working web app.
- **Current goal (5th sem):** turn it into a **professional cross-platform desktop app**
  (Windows + Linux) with offline LLM support, multiple LLM providers, hybrid search,
  reranking, and performance modes — all using **free** tools and APIs (zero budget).
- **Author:** Jeevan Varma R. Solo developer building primarily with AI coding assistants.

**Design north star:** A user should install ONE thing and have it work. No requiring them to
separately install Python, Node, Ollama, or Tesseract. Everything ships inside the app.

---

## 2. Two target machines (this drives every performance decision)

| Machine | Specs | Role |
|---|---|---|
| **Dev / Power** | 16 GB RAM, RTX 3060 GPU, i5 | Build here; runs heavy local models, GPU. |
| **Test / Lite** | 8 GB RAM, **no GPU**, i3 | Mirrors college-lab & typical enterprise PCs. **Must run smoothly here.** |

**Rule:** the default experience must be fast on the 8 GB no-GPU machine. Heavy features
(local LLM, GPU reranking, OCR) are opt-in via a **Power mode** toggle. Always test the Lite
path. See the Lite/Balanced/Power profiles in `IMPLEMENTATION_PLAN.md`.

---

## 3. Architecture

```
frontend/                  React 19 + Vite 7 + TypeScript + Tailwind v4 + Framer Motion
backend/
  main.py                  FastAPI app — all REST endpoints, CORS, upload orchestration
  services/
    document_processing.py PDF/Excel/CSV/image/txt extraction + chunking
    indexing.py            VectorStoreManager — FAISS + metadata.json
    generation.py          RAGPipeline — the retrieval + LLM logic
  uploads/                 raw uploaded files (gitignored)
  vector_store/            FAISS index.faiss + index.pkl + metadata.json (gitignored)
```

Frontend talks to backend over HTTP (currently `http://localhost:8000`, hardcoded — **this
must become configurable**, see plan Phase 0).

### Current RAG pipeline (in `generation.py`)
```
user query
  └─ history-aware rewrite (make follow-ups standalone)
       └─ multi-query: LLM generates 3 variations
            └─ each variation → MMR retrieval (k=5, fetch_k=20, lambda=0.6)
                 └─ Reciprocal Rank Fusion → top 6 chunks
                      └─ (+ exact CSV/Excel numeric-ID lookup prepended to context)
                           └─ Groq LLM → markdown answer + sources
```

### Key components
- **Embeddings:** `all-MiniLM-L6-v2` via a pluggable backend (`services/embeddings.py`).
  Default `sentence-transformers` (pulls `torch` ~2 GB); torch-free `fastembed` (ONNX) is now
  selectable in Settings → Embeddings (and via the `embedding_backend` setting). Switching
  backends needs a re-index — `POST /api/index/rebuild` (atomic; preserves text + citations).
- **Vector store:** FAISS (CPU). `delete_by_source` rebuilds the whole index (O(n)).
- **LLM:** Groq only, via `langchain-groq`. To be abstracted behind a provider layer.
- **State:** `metadata.json` for the doc registry. No DB yet (SQLite planned).

---

## 4. How to run (development)

**Backend** (Python 3.11 recommended):
```bash
cd backend
python -m venv venv
venv/Scripts/activate        # Windows (bash); on Linux: source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

One-click (Windows): `START_PROJECT.bat`. API key lives in `backend/.env` as `GROQ_API_KEY`
(see Security below — this is being moved into the app).

---

## 5. Conventions & expectations for agents

- **Match the surrounding style.** The backend uses clear section-comment banners
  (`# ───`), docstrings on every function, and small focused services. The frontend uses
  functional components, Tailwind utility classes, lucide-react icons, framer-motion.
  Keep new code consistent with this.
- **Cross-platform from now on.** No hardcoded `C:\...` paths, no hardcoded `localhost`.
  Use `pathlib` + OS-appropriate app-data dirs (`platformdirs`) on the backend. The frontend
  must read the backend URL/port from config/env, never a literal.
- **Keep the Lite path working.** Before adding a heavy dependency, ask: does this run on
  8 GB / no GPU? If not, gate it behind Power mode and make it optional at install/runtime.
- **Free only.** No paid APIs or services. Prefer local/open-source; use free API tiers.
- **Don't break the RAG quality.** The multi-query + RRF + exact-lookup combo works well.
  Extend it (hybrid, reranking) rather than replacing it wholesale.
- **Secrets never in code or git.** API keys come from the in-app settings store (planned)
  or a local untracked `.env`. Never commit a key. Never paste a key into docs.
- **Update docs when you change behavior.** Keep `README.md` and this file honest.
- **Prefer small, verifiable steps.** This is a solo + AI workflow; land one coherent change
  at a time and confirm it runs on both the dev machine and (where feasible) the Lite path.

---

## 6. Security note (act on this)

The Groq API key is currently committed in `backend/.env` and pasted in
`TRANSFER_AND_SETUP_GUIDE.md`. **It is exposed and should be rotated** at console.groq.com,
removed from all docs, and `.env` kept out of git (already in `.gitignore`). The long-term
fix is in-app encrypted key storage (plan Phase 1). Do not reintroduce keys into the repo.

---

## 7. Tech decisions already made (don't re-litigate unless asked)

- **Desktop shell:** Tauri 2 (small, cross-platform) wrapping the existing React frontend,
  with the FastAPI backend frozen by PyInstaller and run as a Tauri **sidecar**.
  (Electron is the fallback if Tauri/Rust tooling proves too painful.)
- **Offline LLM without Ollama:** bundle `llama-cpp-python` + a small quantized GGUF model,
  downloaded on first enable. Also auto-detect a user's existing Ollama and use it if present.
- **Multi-provider LLM:** a provider abstraction; most free APIs (DeepSeek, Mistral, Kimi,
  z.ai, OpenRouter) are OpenAI-compatible, so a single OpenAI-compatible client + per-provider
  config covers them; Gemini and local get their own adapters.
- **State DB:** SQLite (drop the unused Postgres config).
- **Embeddings:** migrate to ONNX (`fastembed`) to drop the `torch` dependency for Lite mode.

Full rationale and sequencing: **`IMPLEMENTATION_PLAN.md`**.

---

## 8. Known issues / gotchas

- ~~Frontend backend URL hardcoded~~ — FIXED: resolved at runtime in `frontend/src/api.ts`.
- ~~`mixtral-8x7b-32768` decommissioned~~ — FIXED: model list now lives in `config.PROVIDERS`.
- ~~CORS origins hardcoded~~ — FIXED: `config.CORS_ORIGINS` from `RAG_CORS_ORIGINS` env.
- `delete_by_source` rebuilds the entire FAISS index — fine for small sets, not scalable.
- OCR (`easyocr`, `pytesseract`) needs system Tesseract/Poppler and lots of RAM — keep optional.
- Tests live in `backend/tests/` (pytest). They isolate via `RAG_DATA_DIR` (temp dir set in
  `conftest.py`) so they never touch real uploads/index/history. Run: `cd backend &&
  python -m pytest`. Dev deps: `pip install -r requirements-dev.txt`. Keep adding tests as
  features land (LLM/network paths are intentionally not covered).
- Only 5 files are tracked in git so far; `backend/` and `frontend/` are largely untracked.
  Establish a clean repo state early (plan Phase 0).

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
