"""
Local persistence for chat sessions + history.

Uses Python's built-in `sqlite3` — no extra dependency, no server, works
identically on the 8 GB Lite machine and the packaged desktop app. The DB
file lives at config.DB_PATH (inside DATA_DIR, so it relocates cleanly when
the packaged app sets RAG_DATA_DIR).

A fresh connection is opened per call. SQLite handles this fine for a
single-user desktop app, and per-call connections sidestep the
cross-thread issues you'd hit sharing one connection across FastAPI's
threadpool.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Any, List, Optional

import config


@contextmanager
def _conn():
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now() -> int:
    return int(time.time())


def init_db() -> None:
    """Create tables on first run. Safe to call on every startup."""
    config.ensure_dirs()
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id          TEXT PRIMARY KEY,
                title       TEXT NOT NULL,
                created_at  INTEGER NOT NULL,
                updated_at  INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL,
                role        TEXT NOT NULL,          -- 'user' | 'ai'
                content     TEXT NOT NULL,
                sources     TEXT,                   -- JSON list, nullable
                created_at  INTEGER NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id, id);
            CREATE TABLE IF NOT EXISTS request_metrics (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at      INTEGER NOT NULL,
                provider        TEXT,               -- 'Provider · model' that answered
                prompt_tokens   INTEGER,
                completion_tokens INTEGER,
                total_tokens    INTEGER,
                tokens_estimated INTEGER,           -- 1 if token counts are estimated
                retrieval_ms    REAL,
                generation_ms   REAL,
                total_ms        REAL
            );
            CREATE INDEX IF NOT EXISTS idx_request_metrics_time
                ON request_metrics(created_at);
            """
        )


# ─────────────────────────────────────────────────────────────────────
# Per-request telemetry  (tokens + latency, for the Evaluation Dashboard)
# ─────────────────────────────────────────────────────────────────────
def record_request_metric(metrics: dict) -> None:
    """
    Persist one chat request's telemetry. Best-effort — a telemetry write must
    never be able to break a chat response, so all errors are swallowed.

    `metrics` shape (from RAGPipeline.generate_response_stream's `done` event):
      {"provider": str, "tokens": {"prompt","completion","total","estimated"},
       "retrieval_ms": float, "generation_ms": float, "total_ms": float}
    """
    try:
        tokens = metrics.get("tokens") or {}
        with _conn() as c:
            c.execute(
                "INSERT INTO request_metrics (created_at, provider, prompt_tokens, "
                "completion_tokens, total_tokens, tokens_estimated, retrieval_ms, "
                "generation_ms, total_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _now(),
                    metrics.get("provider"),
                    tokens.get("prompt"),
                    tokens.get("completion"),
                    tokens.get("total"),
                    1 if tokens.get("estimated") else 0,
                    metrics.get("retrieval_ms"),
                    metrics.get("generation_ms"),
                    metrics.get("total_ms"),
                ),
            )
    except Exception:
        pass


def recent_metrics(limit: int = 50) -> List[dict]:
    """Most-recent request metrics, newest first (for the dashboard trends)."""
    try:
        with _conn() as c:
            rows = c.execute(
                "SELECT created_at, provider, prompt_tokens, completion_tokens, "
                "total_tokens, tokens_estimated, retrieval_ms, generation_ms, total_ms "
                "FROM request_metrics ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def metrics_summary() -> dict:
    """Aggregate telemetry (counts, averages) for the dashboard header cards."""
    try:
        with _conn() as c:
            row = c.execute(
                "SELECT COUNT(*) AS n, AVG(total_tokens) AS avg_tokens, "
                "AVG(total_ms) AS avg_total_ms, AVG(generation_ms) AS avg_gen_ms, "
                "AVG(retrieval_ms) AS avg_retrieval_ms FROM request_metrics"
            ).fetchone()
        d = dict(row) if row else {}
        return {
            "requests": d.get("n") or 0,
            "avg_tokens": round(d["avg_tokens"], 1) if d.get("avg_tokens") else 0,
            "avg_total_ms": round(d["avg_total_ms"], 1) if d.get("avg_total_ms") else 0,
            "avg_generation_ms": round(d["avg_gen_ms"], 1) if d.get("avg_gen_ms") else 0,
            "avg_retrieval_ms": round(d["avg_retrieval_ms"], 1) if d.get("avg_retrieval_ms") else 0,
        }
    except Exception:
        return {"requests": 0, "avg_tokens": 0, "avg_total_ms": 0,
                "avg_generation_ms": 0, "avg_retrieval_ms": 0}


# ─────────────────────────────────────────────────────────────────────
# Sessions
# ─────────────────────────────────────────────────────────────────────
def create_session(title: Optional[str] = None) -> dict:
    sid = uuid.uuid4().hex
    now = _now()
    title = (title or "New chat").strip() or "New chat"
    with _conn() as c:
        c.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (sid, title, now, now),
        )
    return {"id": sid, "title": title, "created_at": now, "updated_at": now, "message_count": 0}


def list_sessions() -> List[dict]:
    """All sessions, most recently updated first, with message counts."""
    with _conn() as c:
        rows = c.execute(
            """
            SELECT s.id, s.title, s.created_at, s.updated_at,
                   COUNT(m.id) AS message_count
            FROM sessions s
            LEFT JOIN messages m ON m.session_id = s.id
            GROUP BY s.id
            ORDER BY s.updated_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def rename_session(session_id: str, title: str) -> bool:
    title = (title or "").strip()
    if not title:
        return False
    with _conn() as c:
        cur = c.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title, _now(), session_id),
        )
        return cur.rowcount > 0


def delete_session(session_id: str) -> bool:
    with _conn() as c:
        c.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        cur = c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return cur.rowcount > 0


# ─────────────────────────────────────────────────────────────────────
# Messages
# ─────────────────────────────────────────────────────────────────────
def get_messages(session_id: str) -> List[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT role, content, sources, created_at FROM messages "
            "WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    out = []
    for r in rows:
        out.append({
            "role": r["role"],
            "content": r["content"],
            "sources": json.loads(r["sources"]) if r["sources"] else [],
            "created_at": r["created_at"],
        })
    return out


def add_message(
    session_id: str,
    role: str,
    content: str,
    sources: Optional[List[Any]] = None,
) -> bool:
    """Append a message and bump the session's updated_at. Returns False if the session is gone."""
    now = _now()
    with _conn() as c:
        exists = c.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not exists:
            return False
        c.execute(
            "INSERT INTO messages (session_id, role, content, sources, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content, json.dumps(sources) if sources else None, now),
        )
        c.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
    return True
