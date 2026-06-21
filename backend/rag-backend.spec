# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the Enterprise RAG backend sidecar.

Produces a self-contained ``rag-backend`` executable that the Tauri desktop
shell launches as a sidecar. The shell injects RAG_HOST / RAG_PORT /
RAG_DATA_DIR / RAG_CORS_ORIGINS via the environment, so this binary needs no
arguments — it just serves the FastAPI app (see ``run_server.py``).

Two build flavours, chosen with the RAG_BUILD env var at build time:

    RAG_BUILD=lite   (default)  -> fastembed (ONNX) only; EXCLUDES torch +
                                   sentence-transformers. Small exe, runs on the
                                   8 GB / no-GPU Lite machine. This is the one we
                                   ship by default.
    RAG_BUILD=full              -> bundles torch + sentence-transformers too,
                                   for the Power profile's local embeddings.
                                   Much larger (~2 GB+).

Build (from backend/, with the venv active):

    pyinstaller rag-backend.spec --noconfirm                  # lite
    RAG_BUILD=full pyinstaller rag-backend.spec --noconfirm   # full (bash)
    set RAG_BUILD=full && pyinstaller rag-backend.spec        # full (cmd)

Output: dist/rag-backend(.exe)  — a SINGLE self-contained executable
(one-file). One-file is required so Tauri's ``externalBin`` sidecar mechanism
can place exactly one binary (renamed with the platform target-triple suffix)
into ``src-tauri/binaries/``. The trade-off is a few seconds of self-extraction
on each launch; the desktop shell masks this behind its 60 s health-check /
splash window.
"""

import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files

# ──────────────────────────────────────────────────────────────────────
# Flavour selection
# ──────────────────────────────────────────────────────────────────────
BUILD = os.environ.get("RAG_BUILD", "lite").strip().lower()
FULL = BUILD == "full"
print(f"[spec] RAG_BUILD={BUILD}  (torch/sentence-transformers "
      f"{'INCLUDED' if FULL else 'EXCLUDED'})")

datas = []
binaries = []
hiddenimports = []


def _bundle(pkg):
    """collect_all a package and merge its datas/binaries/hiddenimports."""
    try:
        d, b, h = collect_all(pkg)
        datas.extend(d)
        binaries.extend(b)
        hiddenimports.extend(h)
        print(f"[spec] bundled {pkg}: {len(d)} datas, {len(b)} binaries, "
              f"{len(h)} hidden")
    except Exception as exc:  # noqa: BLE001 — a missing optional pkg is fine
        print(f"[spec] skip {pkg}: {exc}")


# Packages that ship data files / dynamic libs PyInstaller won't find by import
# analysis alone. fastembed + onnxruntime + tokenizers are the ONNX embedding
# path (Lite default). faiss ships a compiled .so/.pyd. langchain packages hide
# imports behind dynamic dispatch.
for pkg in [
    "fastembed",
    "onnxruntime",
    "tokenizers",
    "faiss",
    "langchain",
    "langchain_core",
    "langchain_community",
    "langchain_groq",
    "langchain_openai",
    "langchain_text_splitters",
    "tiktoken",
    "tiktoken_ext",
    "rank_bm25",
    "flashrank",
    "huggingface_hub",
    "cryptography",   # encrypted in-app API-key store (Fernet)
]:
    _bundle(pkg)

# Full flavour: add the torch-based local embedding stack.
if FULL:
    for pkg in ["torch", "sentence_transformers", "transformers", "safetensors"]:
        _bundle(pkg)

# Extra hidden imports that import analysis tends to miss.
hiddenimports += [
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "anyio",
    "anyio._backends._asyncio",
    "fastapi",
    "pydantic",
    "openpyxl",
    "pandas",
    "PIL",
    "PIL.Image",
    # local services (some are imported lazily inside functions)
    "services.system_info",
    "services.providers",
    "services.embeddings",
    "services.reranker",
    "services.storage",
    "services.keystore",
    "services.document_processing",
    "services.indexing",
    "services.generation",
]

# Our own backend data: the default settings template, if present, plus any
# bundled small models directory. (uploads/ and vector_store/ are user data and
# must NOT be frozen in — they live in RAG_DATA_DIR at runtime.)
for rel in ["config.py"]:
    if os.path.exists(rel):
        pass  # config.py is a module, picked up by import analysis — no datas.

# Exclude the heavy torch stack from the lite build so it doesn't get dragged
# in transitively (e.g. via sentence-transformers being importable).
excludes = []
if not FULL:
    excludes += [
        "torch",
        "torchvision",
        "torchaudio",
        "sentence_transformers",
        "transformers",
        # GUI/test frameworks we never need in the sidecar
        "tkinter",
        "matplotlib",
        "pytest",
        "IPython",
        "notebook",
    ]
else:
    excludes += ["tkinter", "matplotlib", "pytest", "IPython", "notebook"]


block_cipher = None

a = Analysis(
    ["run_server.py"],
    pathex=[os.path.abspath(".")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── One-file EXE ────────────────────────────────────────────────────
# All binaries + datas are folded into a single executable so it drops cleanly
# into Tauri's externalBin sidecar slot. (No COLLECT step → no _internal/ dir.)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="rag-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,            # UPX can corrupt onnxruntime/torch DLLs — keep off.
    runtime_tmpdir=None,  # extract to the OS temp dir at launch.
    console=True,         # keep a console for sidecar log capture by the shell.
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
