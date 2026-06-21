"""Tests for the reranker fallbacks and SQLite chat storage."""

from langchain_core.documents import Document

from services import reranker, storage


# ── Reranker ────────────────────────────────────────────────────────
def test_rerank_empty_passthrough():
    assert reranker.rerank("q", [], top_n=5) == []


def test_rerank_truncates_to_top_n():
    docs = [Document(page_content=f"chunk {i}") for i in range(10)]
    out = reranker.rerank("anything", docs, top_n=3)
    assert len(out) == 3
    assert all(isinstance(d, Document) for d in out)


def test_is_available_returns_bool():
    assert isinstance(reranker.is_available(), bool)


# ── Storage (SQLite) ────────────────────────────────────────────────
def test_session_crud_roundtrip():
    storage.init_db()
    s = storage.create_session("test chat")
    sid = s["id"]

    assert storage.add_message(sid, "user", "hello") is True
    assert storage.add_message(sid, "ai", "hi there", sources=[{"file": "x.txt", "chunk": 1}]) is True

    msgs = storage.get_messages(sid)
    assert [m["role"] for m in msgs] == ["user", "ai"]
    assert msgs[1]["sources"][0]["file"] == "x.txt"

    listing = {x["id"]: x for x in storage.list_sessions()}
    assert listing[sid]["message_count"] == 2

    assert storage.rename_session(sid, "renamed") is True
    assert {x["id"]: x["title"] for x in storage.list_sessions()}[sid] == "renamed"

    assert storage.delete_session(sid) is True
    assert sid not in {x["id"] for x in storage.list_sessions()}


def test_add_message_to_missing_session_returns_false():
    storage.init_db()
    assert storage.add_message("nonexistent-id", "user", "hi") is False
