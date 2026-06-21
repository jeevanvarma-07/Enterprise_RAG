#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Build the Enterprise RAG desktop app end to end (Linux / macOS / Git-Bash).
#
#   1. Freeze the FastAPI backend into a single executable (PyInstaller).
#   2. Place it in src-tauri/binaries/ with the Rust target-triple suffix that
#      Tauri's externalBin sidecar expects.
#   3. Build the Tauri app (frontend bundle + installers).
#
# Usage:
#   scripts/build-desktop.sh            # Lite build (fastembed, no torch)
#   RAG_BUILD=full scripts/build-desktop.sh   # Power build (bundles torch)
#
# Prereqxs (see PHASE4_PACKAGING.md): Rust + cargo, the Tauri CLI (installed as
# an npm devDependency already), Python venv with backend deps + pyinstaller,
# and on Linux the webkit2gtk / appimage system libs.
# ---------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
BIN_DIR="$FRONTEND/src-tauri/binaries"
RAG_BUILD="${RAG_BUILD:-lite}"

echo "==> Enterprise RAG desktop build  (flavour: $RAG_BUILD)"

# --- locate the venv python --------------------------------------------------
if [[ -x "$BACKEND/venv/Scripts/python.exe" ]]; then
  PY="$BACKEND/venv/Scripts/python.exe"        # Windows venv layout
elif [[ -x "$BACKEND/venv/bin/python" ]]; then
  PY="$BACKEND/venv/bin/python"                # POSIX venv layout
else
  echo "!! No backend venv found at $BACKEND/venv — create it and pip install -r requirements.txt"
  exit 1
fi

# --- determine the Rust target triple ---------------------------------------
if ! command -v rustc >/dev/null 2>&1; then
  echo "!! rustc not found. Install Rust from https://rustup.rs and re-run."
  exit 1
fi
TRIPLE="$(rustc -Vv | sed -n 's/^host: //p')"
echo "==> Rust target triple: $TRIPLE"

# --- 1. freeze the backend ---------------------------------------------------
echo "==> Freezing backend with PyInstaller ..."
( cd "$BACKEND" && RAG_BUILD="$RAG_BUILD" "$PY" -m PyInstaller rag-backend.spec \
    --noconfirm --distpath dist --workpath build_pyi )

# --- 2. place the sidecar with the target-triple name ------------------------
mkdir -p "$BIN_DIR"
if [[ "$TRIPLE" == *windows* ]]; then
  SRC="$BACKEND/dist/rag-backend.exe"
  DST="$BIN_DIR/rag-backend-$TRIPLE.exe"
else
  SRC="$BACKEND/dist/rag-backend"
  DST="$BIN_DIR/rag-backend-$TRIPLE"
fi
if [[ ! -f "$SRC" ]]; then
  echo "!! Expected frozen binary not found at $SRC"
  exit 1
fi
cp -f "$SRC" "$DST"
chmod +x "$DST" 2>/dev/null || true
echo "==> Sidecar staged: $DST"

# --- 3. build the Tauri app --------------------------------------------------
echo "==> Building Tauri app ..."
( cd "$FRONTEND" && npm run tauri:build )

echo "==> Done. Installers are under frontend/src-tauri/target/release/bundle/"
