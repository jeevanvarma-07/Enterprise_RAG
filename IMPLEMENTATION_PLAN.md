# Enterprise RAG — 5th Semester Implementation Plan

**Goal:** Evolve the working 4th-sem web app into a **professional, cross-platform desktop
application** (Windows + Linux) that is offline-capable, multi-provider, advanced (hybrid
search + reranking), and runs well on low-spec machines — built entirely with **free** tools.

**Read `CLAUDE.md` first** for architecture and conventions. This file is the roadmap.

---

## 0. Guiding principles

1. **Architecture app-aware now, package last.** Do the structural refactors (provider layer,
   settings, SQLite, configurable URLs) while it's still a fast-to-iterate web app. Build
   features in the browser. Package into a desktop app only once the feature set is stable.
2. **Lite-first.** Default experience must be smooth on 8 GB RAM / no GPU / i3 (college-lab
   spec). Heavy capability is opt-in via **Power mode**.
3. **One install, no prerequisites.** Ship Python, Node, Tesseract/Poppler, and (optional)
   a local model *inside* the app. The user installs one file.
4. **Zero budget.** Free/open-source and free API tiers only.
5. **Don't regress RAG quality.** Extend the existing multi-query + RRF + exact-lookup
   pipeline; don't rip it out.

### Recommended ordering (the answer to "features first or app first?")
```
Phase 0  Foundation & app-aware refactor   ← do now, still a web app
Phase 1  Multi-provider + offline LLM      ← biggest "wow", design-once
Phase 2  Advanced RAG (hybrid, rerank, stream, persistence)
Phase 3  Performance modes + Lite optimization
Phase 4  Desktop packaging (Tauri + PyInstaller)
Phase 5  Professional polish & release
(Later)  Mobile
```

---

## Phase 0 — Foundation & app-aware refactor

*Goal: clean base + remove every assumption that breaks once packaged. Still runs as a web app.*

- [ ] **Repo hygiene.** Establish a clean git state. Confirm `venv/`, `node_modules/`,
      `uploads/`, `vector_store/`, `.env` are gitignored (they are) and untracked. Commit the
      real source tree (`backend/`, `frontend/`). Add a proper `README` for v3.
- [ ] **Rotate & remove secrets.** Rotate the exposed Groq key at console.groq.com. Delete the
      key from `TRANSFER_AND_SETUP_GUIDE.md` and from `backend/.env` in git history if it was
      ever committed. Keys will live in the in-app settings store (Phase 1).
- [ ] **Settings/config system.** Add a `config/` module: a typed settings object loaded from
      a JSON/SQLite store in the OS app-data dir (use `platformdirs`), with sane defaults.
      Controls: active provider, model, mode (Lite/Balanced/Power), paths, feature flags.
- [ ] **SQLite state.** Introduce SQLite (stdlib `sqlite3` or SQLModel) for: settings, chat
      sessions + messages, document registry (replacing `metadata.json` over time).
      **Remove the unused Postgres config** from `.env` and `docker-compose.yml`.
- [ ] **Configurable backend URL.** Frontend must read the API base URL/port from a runtime
      config (env var in dev, injected value in the packaged app), not a hardcoded
      `http://localhost:8000`. Centralize it in one `api.ts` axios client.
- [ ] **Cross-platform paths.** Replace any `C:\`-style or relative-cwd assumptions with
      `pathlib` + app-data dirs. Uploads/vector store live under a per-user data dir, not the
      repo, in the packaged build.
- [ ] **Fix stale model list.** Remove decommissioned `mixtral-8x7b-32768`; populate the model
      dropdown from the provider layer (Phase 1) instead of a hardcoded list.
- [ ] **Dynamic CORS.** Drive CORS origins from config (dev allows localhost; packaged app
      uses the Tauri origin).

**Exit criteria:** app runs identically to today, but with no hardcoded URLs/paths, secrets
out of the repo, settings + SQLite in place, and a single axios client.

---

## Phase 1 — Multi-provider LLM + offline support

*Goal: user picks from many free cloud models OR runs fully offline — no Ollama install required.*

- [ ] **Provider abstraction.** `backend/services/providers/` with a common interface
      (`chat(messages, model, stream) -> tokens`). Adapters:
  - **OpenAI-compatible** (one adapter, many providers via base_url + key):
    Groq, DeepSeek, Mistral, Moonshot/Kimi, z.ai, OpenRouter, OpenCode Zen, Wafer.
  - **Google Gemini** (Google AI Studio) — own adapter (or its OpenAI-compat endpoint).
  - **Local llama.cpp** — `llama-cpp-python`, loads a bundled/downloaded GGUF, GPU offload
    when available.
  - **Ollama auto-detect** — if a local Ollama server is running, list & use its models.
  - *(Optional: evaluate `litellm` to collapse the cloud adapters into one dependency.)*
- [x] **In-app API-key management.** ✅ Settings → LLM Providers lets you paste a key
      per provider; it's **Fernet-encrypted at rest** (`services/keystore.py`) under the
      per-user data dir (`secret.key` + `keys.enc`), never in the repo or a plaintext
      `.env`. `config.provider_api_key()` resolves the encrypted store first, then the
      env fallback, so `provider_is_configured` / the model picker light up automatically.
      Endpoints: `POST`/`DELETE /api/providers/{name}/key`; `GET /api/providers` reports
      `has_stored_key` + `key_storage_available` (never the secret). Degrades gracefully
      if `cryptography` is absent. (Done 2026-06-22.)
- [ ] **Model picker UI.** Replace the static dropdown with provider → model selection,
      populated dynamically (cloud model lists + detected local/Ollama models).
- [ ] **Offline mode (no Ollama needed).** Bundle `llama-cpp-python`. On first "Enable
      offline" the app downloads a small quantized GGUF (e.g. Qwen2.5-3B-Instruct or
      Llama-3.2-3B, Q4_K_M ~2 GB) to the app-data dir. GPU offload on the 3060; on the 8 GB
      laptop keep cloud as default and warn that local will be slow.
- [x] **Graceful fallback.** ✅ When the chosen provider can't build (missing key) or
      errors at generation (rate-limit / network / offline), the pipeline transparently
      retries the next *configured* provider's default model. `providers.fallback_candidates()`
      gives a deterministic order (chosen first, then other configured providers); generation
      handles both build-time (`_build_first_working`) and runtime (`_invoke_with_fallback` /
      streaming `_stream_with_fallback`, which falls back only before the first token) failures,
      and a `notice` (JSON field + SSE `notice` event) tells the user which provider answered.
      Gated by `config.fallback_enabled()` (`llm_fallback` setting, on by default); a single
      configured provider behaves exactly as before. 16 new tests. Done 2026-06-22.
- [ ] **Embedding provider choice.** Allow local embeddings (default) or a free embedding API,
      mirroring the LLM abstraction (keeps offline truly offline).

**Exit criteria:** switch freely between ≥3 cloud providers and 1 local model; keys managed
in-app; offline chat works on the dev machine with no external services.

---

## Phase 2 — Advanced RAG

*Goal: measurably better retrieval and UX. Builds on the existing RRF infrastructure.*

- [x] **Hybrid search.** ✅ BM25 keyword retrieval (`rank_bm25`) fused with FAISS dense
      retrieval via the existing RRF. Cached in `VectorStoreManager`, invalidated on
      add/delete/clear, degrades to dense-only if unavailable. (Exact CSV/ID lookup stays
      as a third signal.) Done 2026-06-21.
- [x] **Reranking.** ✅ Optional cross-encoder rerank of the fused candidates before the
      LLM, via `flashrank` (tiny ONNX cross-encoder `ms-marco-MiniLM-L-12-v2`, no torch,
      model auto-downloaded into `MODELS_DIR`). `services/reranker.py` is a lazy singleton
      that degrades to plain fusion order if the package/model is unavailable — chat never
      breaks. Gated by `config.rerank_enabled()`: OFF for Lite, ON for balanced/power (auto),
      overridable via the `rerank` setting (`auto|on|off`) or `RAG_RERANK_*` env. Done 2026-06-21.
- [x] **Streaming responses.** ✅ Token streaming over SSE (`/api/chat/stream`,
      `generate_response_stream`); frontend consumes the `ReadableStream` and grows the AI
      bubble live, with a `sources` event first. Done 2026-06-21.
- [x] **Better citations.** ✅ Chunk metadata now carries location: PDFs tag `page`,
      Excel/CSV tag `rows` (e.g. "16-30"). `process_document_chunks` returns (text, meta)
      pairs (back-compat `process_document` kept); `add_documents` merges meta into each
      Document; sources expose a `location` string shown as a chip in the UI. New uploads
      get this; pre-existing indexed docs simply have no location. Sources now also carry the
      full chunk `text`; clicking a source opens a modal showing the exact retrieved context.
      Done 2026-06-21.
- [x] **Chat persistence.** ✅ Sessions + history in SQLite (`services/storage.py`, stdlib
      `sqlite3`, no dep) with full session CRUD endpoints in `main.py`. Frontend
      `SessionsPanel` sidebar (browse/select/rename/delete + New chat); `ChatInterface`
      loads history on session switch and saves each exchange after streaming, creating a
      session titled from the first question. Done 2026-06-21.
- [x] **Retrieval tuning surface.** ✅ Live knobs in the Settings → *Retrieval Tuning* panel:
      `top_k`, `fetch_k`, `mmr_lambda`, `bm25_k` (0 disables sparse), `final_k`,
      `rerank_candidates`. Persisted in settings; `config.retrieval_params()` coerces + clamps
      each to a safe range; `generation._multi_query_retrieve` reads them live (no re-index).
      Defaults mirror the old hardcoded values, so Lite behavior is unchanged. Sliders commit
      on release; "Reset to defaults" included. Done 2026-06-21.
- [x] **Evaluation harness.** ✅ `backend/scripts/eval_retrieval.py` measures the retrieval
      layer (dense + BM25 + RRF + optional rerank, no LLM → offline/deterministic) and reports
      Recall@k + MRR per config preset (dense-only / hybrid / hybrid+rerank). Runs zero-setup
      on a built-in synthetic corpus, or against the real store with `--use-store --dataset
      eval/<file>.json` (example in `backend/eval/example_questions.json`). Covered by
      `tests/test_eval_harness.py`. Done 2026-06-21.

**Exit criteria:** hybrid + rerank demonstrably improve answers on your test docs; responses
stream; conversations persist across restarts.

---

## Phase 3 — Performance modes & Lite optimization

*Goal: one app that scales from the i3/8 GB lab PC to the 3060 desktop.*

- [x] **Define profiles** (selectable in settings, auto-suggested from detected hardware). ✅
      `config.MODE_PROFILES` (lite/balanced/power) bundles per-mode `rerank`, `ocr`,
      `upload_concurrency`, and a suggested `embedding` backend. Helpers `active_mode()`,
      `ocr_enabled()`, `upload_concurrency()`; `rerank_enabled()` now reads the same table.
      Settings → Performance Mode shows the cards + detected hardware + one-click "Apply
      suggested". Done 2026-06-21.

  | Setting | **Lite** (8 GB, no GPU) | **Balanced** | **Power** (16 GB + GPU) |
  |---|---|---|---|
  | Embeddings | ONNX `fastembed` (CPU) | ONNX `fastembed` | `sentence-transformers` / GPU |
  | LLM | Cloud (free API) | Cloud | Local GGUF (GPU) or cloud |
  | Reranking | off / free API | ONNX cross-encoder | local `bge-reranker` (GPU) |
  | Hybrid search | on (BM25 is cheap) | on | on |
  | OCR (images/scans) | off by default | on (pytesseract) | on (easyocr/GPU) |
  | Upload concurrency | low | medium | high |

- [x] **Drop torch for Lite — the ONNX path is live and selectable.** The torch-free
      `fastembed` backend (same `all-MiniLM-L6-v2`, same 384-dim space) now works end-to-end:
      - `services/embeddings.py` is a pluggable backend (`get_embeddings()` + `signature()`),
        selected via the `embedding_backend` setting (default `sentence-transformers`, optional
        `fastembed` with graceful fallback). `indexing.py` stamps the backend+model into
        `embedding_info.json` next to the index and **warns on load if it changed**.
      - `fastembed` added to `requirements.txt` (optional/Lite note). Verified: ONNX embedder
        returns real 384-dim vectors; eval-harness parity = identical recall/MRR to
        sentence-transformers on the synthetic set.
      - **Re-index path:** `VectorStoreManager.rebuild_embeddings()` (atomic temp-dir swap,
        preserves chunk text + citations + URL-scraped sources) exposed at
        `POST /api/index/rebuild` (runs in a threadpool).
      - **Settings UI:** new "Embeddings" section — pick Accurate (torch) vs Light (ONNX) and a
        "Rebuild index" button that re-embeds in place. 42 backend tests pass.
      - Remaining for full Lite packaging: ship a Lite build that installs `fastembed` and NOT
        `torch` (a PyInstaller/extras decision, deferred to Phase 4 packaging).
- [x] **Hardware auto-detect.** ✅ `services/system_info.py` detects RAM (psutil → stdlib
      ctypes/sysconf fallback), CPU count, and GPU (`nvidia-smi`, no heavy imports) and maps
      them to a suggested profile. Exposed at `GET /api/system`; the Settings panel surfaces it
      with an "Apply suggested" button. Never raises — degrades to a Lite suggestion. Done 2026-06-21.
- [x] **Make OCR optional.** ✅ `pytesseract`/`pdf2image` are now defensive imports
      (`TESSERACT_AVAILABLE`/`PDF2IMAGE_AVAILABLE`) so a missing OCR stack no longer breaks
      *uploads of normal PDFs/Excel/txt*. All OCR paths gate on `_ocr_ready()` =
      installed AND `config.ocr_enabled()` (off on Lite, auto-on for Balanced/Power, with an
      `ocr` auto|on|off override in Settings). Done 2026-06-21.
- [~] **Lazy loading & memory care.** Embedding + reranker are already lazy singletons that
      load on first use; OCR is now skipped entirely on Lite. Per-mode `upload_concurrency` is
      defined in the profile (not yet throttling ingestion — deferred: needs serialized FAISS
      writes to stay safe). Peak-RAM verification on the 8 GB laptop still pending.
- [ ] **Profile on the laptop.** Measure cold start, index time, and query latency on the
      8 GB/no-GPU machine; fix the worst offenders.

**Exit criteria:** Lite profile runs smoothly on the laptop; Power profile uses the GPU; mode
switch changes behavior live.

---

## Phase 4 — Desktop packaging (Windows + Linux)

*Goal: a single installer per OS. No Python/Node/Ollama/Tesseract prerequisites.*

- [x] **Shell: Tauri 2** wrapping the existing React build. ✅ Scaffolded at
      `frontend/src-tauri/` (Cargo.toml, tauri.conf.json, build.rs, `src/lib.rs` + `main.rs`,
      capabilities, generated icons). The Rust shell (`lib.rs`) picks a free port, spawns the
      sidecar, polls `/api/health` (≤60 s), then creates the webview injecting
      `window.__RAG_API_BASE__`; kills the backend on window-close/exit. CLI installed as an npm
      devDependency (`@tauri-apps/cli` 2.11). Done 2026-06-21.
- [x] **Backend sidecar: PyInstaller.** ✅ `backend/rag-backend.spec` freezes FastAPI + services
      into a **single one-file** exe via `backend/run_server.py` (uvicorn, no reload, honours
      `RAG_PORT`/`RAG_HOST`/`RAG_DATA_DIR`). Lite flavour (fastembed, torch excluded) = **138 MB**;
      `RAG_BUILD=full` adds torch. **Validated:** the frozen exe boots on an injected port and
      serves `/api/health` → 200 with the per-user data dir. Done 2026-06-21.
- [x] **Per-user data dir.** ✅ The shell sets `RAG_DATA_DIR` to the OS app-data dir
      (`%APPDATA%\com.jeevanvarma.enterpriserag\data` / `~/.local/share/…`); `config.py` already
      routes uploads/vector_store/settings.json/rag.db there. Verified live. Done 2026-06-21.
- [x] **Installers + CI.** ✅ One-command build scripts (`scripts/build-desktop.ps1` / `.sh`)
      freeze → stage the triple-named sidecar → `tauri build`. `tauri.conf.json` targets
      Windows `nsis`+`msi` and Linux `appimage`+`deb`. `.github/workflows/desktop-build.yml`
      builds both OSes on a `v*` tag. Done 2026-06-21.
- [x] **Lifecycle.** ✅ Backend killed on `CloseRequested` + `ExitRequested`; free-port pick
      avoids port-in-use; the 60 s health-check window covers slow cold starts. Done 2026-06-21.
- [ ] **Bundle native deps.** Tesseract/Poppler binaries for OCR (or ship as optional add-on),
      and the `llama-cpp-python` runtime for offline mode. *(OCR stays opt-in/Power-gated; not
      needed for the Lite default — deferred.)*
- [x] **First-run wizard.** ✅ `frontend/src/components/FirstRunWizard.tsx` — a 3-step portal
      modal shown once (gated on the new `onboarded` setting): privacy-first welcome → pick
      performance mode (pre-selected from `/api/system` hardware detection, applied via
      `/api/settings`) → optionally paste an API key (saved to the encrypted keystore via
      `POST /api/providers/{name}/key`). Fully skippable; degrades gracefully when the backend
      is offline or key storage is unavailable; completing it persists `{onboarded: true}`.
      Offline-model download stays deferred (Power-gated). Done 2026-06-22.

**Exit criteria:** double-click installer on a clean Windows and a clean Linux machine →
working app, cloud chat out of the box, no manual setup.
**Status (2026-06-22):** ✅ **Windows installers built** — Rust 1.96.0 (stable-msvc) installed
and `tauri build` produced `Enterprise RAG_2.0.0_x64-setup.exe` (NSIS) + `…_x64_en-US.msi`
under `frontend/src-tauri/target/release/bundle/`. Fixed a clean-install boot crash on the
Lite freeze (default embedding backend fell back to fastembed; see `PHASE4_PACKAGING.md` §6).
First-run wizard landed 2026-06-22 (see above). Remaining: Linux `.AppImage`/`.deb` (build on a
Linux host or via the `v*`-tag CI workflow); end-to-end smoke test of the installed app; the
deferred OCR/llama.cpp native bundling.

---

## Phase 5 — Professional polish & release

*Goal: something an enterprise or buyer would take seriously.*

- [ ] **Branding & UX:** product name, logo, app icon, consistent empty/error/loading states,
      keyboard shortcuts, dark/light theme.
- [~] **Robust error handling:** chat surfaces server error detail (not a generic "port 8000"
      message) and distinguishes network vs server failures; missing-key errors point to
      Settings → LLM Providers (not the dev-only `.env`); empty-index/no-results return friendly
      guidance; OCR/offline deps fail soft. **Prompt-size budget** (`config.prompt_budget`,
      Settings → *Request Size*) caps re-sent history (`history_turns`) and retrieved context
      (`context_chars`) so a long chat or big index can't trip a provider's tokens-per-minute
      limit (Groq free tier = 6,000 TPM → the 413 "Request too large"). (Done 2026-06-22.)
      *Remaining: a sweep of the upload/download/rebuild paths.*
- [x] **Privacy posture:** ✅ Stated in the first-run wizard and the in-app Help panel —
      documents/index/history stay local; only the chosen cloud LLM prompt leaves; offline mode
      sends nothing. Done 2026-06-22.
- [~] **Onboarding & docs:** ✅ First-run wizard + an always-available in-app **Help & About**
      panel (getting-started, privacy, modes, version, project link). Done 2026-06-22.
      *Remaining: a standalone user guide / one-page site.*
- [~] **Tests & CI:** ✅ 60 backend tests (config, doc processing, indexing, generation,
      embeddings, modes, reranker/storage, keystore, eval harness) isolated via a temp
      `RAG_DATA_DIR`. `.github/workflows/backend-tests.yml` runs the suite on push/PR to main
      across Python 3.9 + 3.11. (Done 2026-06-22.) *Remaining: a boot smoke-test of the packaged
      app in CI.*
- [ ] **Licensing:** choose a license (consider a source-available or dual license if you want
      to sell it later). Add `LICENSE` and third-party attributions.
- [ ] **Versioning & auto-update:** semantic versions, release notes; Tauri updater later.
- [ ] **Optional pro features** (differentiators): folder watch/auto-index, export
      chat-to-PDF, multi-collection workspaces, role-based document sets, audit log.

**Exit criteria:** a versioned v3.0 release with installers, docs, and a clean first-run story.

---

## Later — Mobile

Defer until desktop is solid. Likely path: keep the FastAPI backend, build a separate mobile
frontend (React Native / Tauri Mobile / Flutter) that points at a self-hosted or cloud backend
(mobile devices can't run the heavy local pipeline). Decide based on whether "offline on phone"
matters; if not, mobile is a thin client to a server you host.

---

## Tooling notes for AI-assisted building

- **This file + `CLAUDE.md` are the shared context** across Claude Code, Cursor, and
  Antigravity. Point each tool at them at the start of a session.
- **Work phase by phase, small commits.** Land one checklist item, verify it runs on the dev
  machine, and (for Lite-affecting changes) on the laptop, before moving on.
- **Spread free API usage** across your providers (Groq/Gemini/DeepSeek/Mistral/Kimi/z.ai/
  OpenRouter) to stay within free limits during development.
- **Keep secrets out of the repo and out of prompts/docs** — always.

## Open decisions to confirm as you go
- Which small GGUF model to bundle for offline (size vs quality on the 3060).
- `litellm` vs hand-rolled OpenAI-compatible adapter for the cloud providers.
- Stay on FAISS, or move to an embedded vector DB (LanceDB/Chroma) for easier delete/update.
- Tauri vs Electron final call (try Tauri first; switch only if Rust tooling blocks you).
