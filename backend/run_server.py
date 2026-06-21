"""
Production / frozen-app entrypoint for the Enterprise RAG backend.

Why this exists separately from `main.py`'s ``if __name__ == "__main__"``:
the dev block uses ``reload=True``, which spawns a reloader subprocess and
relies on an importable module path — neither works inside a PyInstaller
one-file executable. This entrypoint runs uvicorn programmatically against the
already-imported ``app`` object, with reload OFF, honouring the same
RAG_HOST / RAG_PORT environment variables the Tauri shell injects.

The desktop shell launches the frozen sidecar like:

    rag-backend.exe            # uses RAG_HOST/RAG_PORT from the environment

so the only contract here is "read config.HOST / config.PORT and serve".
"""

from __future__ import annotations

import sys

import uvicorn

import config
from main import app


def main() -> None:
    """Start the API server on the configured host/port (no reload)."""
    # Make sure the per-user data directories exist before serving. (main.py
    # also calls this at import time; harmless to be explicit for the frozen
    # build where import side-effects are easy to overlook.)
    config.ensure_dirs()

    # Log the bind target to stdout so the desktop shell can confirm the port
    # in its sidecar logs.
    print(
        f"[rag-backend] starting on http://{config.HOST}:{config.PORT} "
        f"(data dir: {config.DATA_DIR})",
        flush=True,
    )

    uvicorn.run(
        app,
        host=config.HOST,
        port=config.PORT,
        reload=False,
        log_level="info",
        # PyInstaller-friendly: a single worker in-process, no lifespan tricks.
        workers=1,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
