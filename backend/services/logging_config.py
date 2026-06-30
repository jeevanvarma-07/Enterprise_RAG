# ─────────────────────────────────────────────────────────────────────
# Logging configuration
# ─────────────────────────────────────────────────────────────────────
# Central logging setup for the backend. Replaces the old `print()` strategy
# with the stdlib `logging` module so we get levels, timestamps, module names,
# and — crucially for diagnosing field issues — a rotating log file under the
# per-user data dir. The packaged (Tauri) app drains stdout to a hidden console,
# so the file handler is the only durable record of what happened on a user's
# machine.
#
# Call `setup_logging()` once at process startup (done in `main.py`). Every other
# module just does `logger = logging.getLogger(__name__)` and logs normally.

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

import config

_CONFIGURED = False

# Override the level via env without code changes (e.g. RAG_LOG_LEVEL=DEBUG).
_DEFAULT_LEVEL = os.getenv("RAG_LOG_LEVEL", "INFO").upper()

_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str | None = None) -> None:
    """
    Configure the root logger with a console handler and a rotating file handler.

    Idempotent: safe to call more than once (e.g. under uvicorn --reload or in
    tests) — handlers are only attached on the first call.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    config.ensure_dirs()  # make sure LOGS_DIR exists before we open a file there

    root = logging.getLogger()
    root.setLevel(getattr(logging, (level or _DEFAULT_LEVEL), logging.INFO))

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    try:
        log_file = config.LOGS_DIR / "app.log"
        file_handler = RotatingFileHandler(
            str(log_file), maxBytes=2_000_000, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except Exception as e:  # disk full / permission — keep console logging working
        root.warning("Could not open log file (%s); logging to console only.", e)

    # uvicorn installs its own handlers; let its loggers propagate to root so all
    # output funnels through our handlers and into the file too.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).propagate = True

    _CONFIGURED = True
