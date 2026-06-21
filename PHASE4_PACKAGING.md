# Phase 4 — Desktop Packaging (Tauri 2 + PyInstaller)

This turns the web app into a **single installable desktop app** for Windows and
Linux. The user installs ONE thing; Python, the backend, the model runtime and
the UI all ship inside it. No separate Python / Node / Ollama / Tesseract
install required.

> **Status:** Fully scaffolded and validated except the final `tauri build`,
> which needs **Rust** on the build machine (see step 1). The backend freeze,
> the sidecar, the health-check handshake and the frontend bundle are all built
> and tested on this machine. Once Rust is installed, `npm run tauri:build`
> produces the installers.

---

## 1. Architecture

```
┌──────────────────────────── Enterprise RAG.exe ────────────────────────────┐
│  Tauri shell (Rust)                                                         │
│    • picks a free localhost port                                            │
│    • sets a per-user data dir  (RAG_DATA_DIR = %APPDATA%\…\EnterpriseRAG)    │
│    • spawns the backend sidecar with that port + data dir in its env        │
│    • polls GET /api/health until ready (≤ 60 s)                             │
│    • opens the WebView2 window, injecting window.__RAG_API_BASE__           │
│    • kills the backend when the window closes                               │
│                                                                             │
│   ┌─────────────────────────┐        ┌────────────────────────────────┐    │
│   │ WebView (React build)   │ HTTP→  │ rag-backend.exe (PyInstaller)  │    │
│   │ frontend/dist           │        │ FastAPI + FAISS + fastembed    │    │
│   └─────────────────────────┘        └────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

- **Frontend ↔ backend contract:** `frontend/src/api.ts` reads
  `window.__RAG_API_BASE__` (injected by the shell) → falls back to
  `VITE_API_BASE_URL` → `http://localhost:8000`. The SAME build runs in dev and
  packaged.
- **Backend config:** `backend/config.py` reads `RAG_HOST`, `RAG_PORT`,
  `RAG_DATA_DIR`, `RAG_CORS_ORIGINS` from the environment. CORS already allows
  `tauri://localhost`. The frozen entrypoint is `backend/run_server.py`
  (uvicorn, no `--reload`).
- **Sidecar packaging:** PyInstaller **one-file** → a single
  `rag-backend(.exe)` placed in `frontend/src-tauri/binaries/` with the Rust
  **target-triple** suffix Tauri requires (e.g.
  `rag-backend-x86_64-pc-windows-msvc.exe`).

---

## 2. What you must install (one-time)

| Tool | Why | Install |
|---|---|---|
| **Rust + cargo** | Tauri compiles a small Rust shell | https://rustup.rs → run `rustup-init`, accept defaults, reopen the terminal |
| WebView2 runtime | The window renderer (Windows) | Pre-installed on Win 10/11. (Verified present on this machine.) |
| Node 18+ / npm | builds the React UI | Already installed (node 22). |
| Python 3.9–3.11 venv | freezes the backend | Already set up in `backend/venv`. |
| PyInstaller | the freezer | Already installed in the venv (`pip install pyinstaller`, also in `requirements-dev.txt`). |
| Tauri CLI | drives the build | Already installed as an npm devDependency (`@tauri-apps/cli`). |

**Linux build host only** also needs the system libraries:
```bash
sudo apt-get install -y libwebkit2gtk-4.1-dev libappindicator3-dev \
  librsvg2-dev patchelf libfuse2 build-essential curl wget file
```

> You only need Rust to be added. Everything else on this machine is ready.

### Verify Rust after installing
```bash
rustc --version      # e.g. rustc 1.x
cargo --version
```

---

## 3. Build the app

### One command (recommended)

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-desktop.ps1
# Power flavour (bundles torch for local embeddings — much larger):
powershell -ExecutionPolicy Bypass -File scripts\build-desktop.ps1 -Flavour full
```

**Linux / macOS / Git-Bash:**
```bash
scripts/build-desktop.sh
RAG_BUILD=full scripts/build-desktop.sh
```

The script: freezes the backend → stages the sidecar with the right triple name
→ runs `tauri build`.

### Manual (if you want to see each step)
```bash
# 1. freeze the backend (from backend/, venv active)
cd backend
RAG_BUILD=lite python -m PyInstaller rag-backend.spec --noconfirm --distpath dist --workpath build_pyi

# 2. stage the sidecar under the triple name (Windows example)
mkdir -p ../frontend/src-tauri/binaries
cp dist/rag-backend.exe ../frontend/src-tauri/binaries/rag-backend-x86_64-pc-windows-msvc.exe

# 3. build the desktop app
cd ../frontend
npm run tauri:build
```

**Output installers:** `frontend/src-tauri/target/release/bundle/`
- Windows: `nsis/*.exe` and `msi/*.msi`
- Linux: `appimage/*.AppImage` and `deb/*.deb`

### Live development (hot-reload UI inside the native window)
```bash
cd frontend
npm run tauri:dev
```
This runs Vite + the Rust shell together. The shell still spawns the **frozen**
sidecar from `binaries/`, so freeze the backend at least once first (step 1).

---

## 4. Build flavours: Lite vs Full

| | Lite (default) | Full |
|---|---|---|
| Env | `RAG_BUILD=lite` | `RAG_BUILD=full` |
| Embeddings | `fastembed` (ONNX, no torch) | + `sentence-transformers` (torch) |
| Frozen size | ~138 MB one-file | ~1–2 GB |
| Target machine | 8 GB / no-GPU (the test laptop) | 16 GB + GPU dev box |

Ship **Lite**. It runs the default Lite performance profile and downloads the
~90 MB MiniLM ONNX model on first embedding (cached under `RAG_DATA_DIR`).
The Power profile inside the app still works for retrieval/reranking; only the
torch-based *local embedding backend* requires a Full build.

---

## 5. Runtime data location (per user)

The shell sets `RAG_DATA_DIR` to the OS app-data dir, so user content never
lives in Program Files:

| OS | Path |
|---|---|
| Windows | `%APPDATA%\com.jeevanvarma.enterpriserag\data` |
| Linux | `~/.local/share/com.jeevanvarma.enterpriserag/data` |

Inside it: `uploads/`, `vector_store/`, `settings.json`, `rag.db`, `models/`.

---

## 6. Built & validated on this machine ✅

- Backend freeze (lite) → `rag-backend.exe`, **~138 MB one-file**.
- Frozen exe boots on an injected `RAG_PORT` **with a fresh data dir**, serves
  `GET /api/health` → `200`, honours `RAG_DATA_DIR`, uses the `fastembed` backend.
- Frontend production build → `frontend/dist` (Tauri `frontendDist`).
- Sidecar staged as `rag-backend-x86_64-pc-windows-msvc.exe`.
- Tauri config, capabilities, Rust shell (`src-tauri/src/lib.rs`), icons: written.
- **Rust 1.96.0 (stable-msvc) installed; `tauri build` run → Windows installers
  emitted** (2026-06-22):
  - `…/release/bundle/nsis/Enterprise RAG_2.0.0_x64-setup.exe` (~138 MB)
  - `…/release/bundle/msi/Enterprise RAG_2.0.0_x64_en-US.msi` (~139 MB)

> **Boot-crash fix (2026-06-22):** the Lite freeze excludes torch, but the default
> `embedding_backend` setting is `sentence-transformers`, so a *clean* install
> (no `settings.json`) crashed at startup with `Could not import sentence_transformers`.
> `services/embeddings.py` now resolves the configured backend to one that is
> actually importable (bidirectional fallback), and `signature()` reflects that
> effective backend so the index stamp stays truthful. Verified: clean boot →
> `"embedding":"fastembed:all-MiniLM-L6-v2"`.

**Remaining (needs a Linux host / CI):** the `.AppImage` / `.deb` Linux bundles —
build via `.github/workflows/desktop-build.yml` on a `v*` tag (Windows can't
produce Linux bundles).

---

## 7. CI (optional, free)

`.github/workflows/desktop-build.yml` builds Windows + Linux installers on a
`v*` tag or manual dispatch, and uploads them as artifacts. It installs Rust,
the Linux system libs, freezes the backend, stages the sidecar, and runs
`tauri build` — the same steps as the local scripts. GitHub Actions minutes are
free for public repos.

---

## 8. Gotchas / notes

- **Antivirus + one-file:** one-file PyInstaller self-extracts to temp on launch
  (a few seconds — the shell's health-check waits up to 60 s). Some AV flags
  unsigned exes; code-signing is a later, paid step (skip for now).
- **`tauri::generate_context!` needs the icons** — they're generated in
  `src-tauri/icons/` (PNG + `.ico`). To regenerate from a source PNG later:
  `cd frontend && npx tauri icon src-tauri/icons/icon-source.png`.
- **macOS** isn't a target (no `.icns`, no mac runner). Add later if needed.
- **Don't commit** `src-tauri/binaries/`, `src-tauri/target/`, `backend/dist/`,
  `backend/build_pyi/` — all gitignored (regenerable, large).
- **Keys:** the packaged app has no `.env`; API keys come from in-app Settings
  (Phase 1 store). Never bundle a key into the installer.
