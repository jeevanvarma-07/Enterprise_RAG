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
            """
        )


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
