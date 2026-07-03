"""
Tests for the Retrieval Inspector, token/latency telemetry, and content-hash
duplicate detection — the transparency + reliability layer added on top of the
core RAG pipeline.

All offline: no network, no LLM, no keys. RetrievalTrace and the usage/estimate
helpers are pure; the storage + indexing tests run against the throwaway
RAG_DATA_DIR / tmp_path that conftest isolates.
"""

from types import SimpleNamespace

import pytest

import config
from services import storage
from services.indexing import VectorStoreManager
from services.document_processing import content_hash
from services.providers import extract_usage, estimate_tokens
from services.inspection import RetrievalTrace, PREVIEW_CHARS


# ─────────────────────────────────────────────────────────────────────
# RetrievalTrace
# ─────────────────────────────────────────────────────────────────────
def _doc(text, source="a.txt", **meta):
    return SimpleNamespace(page_content=text, metadata={"source": source, **meta})


def test_trace_records_stages_into_dict():
    t = RetrievalTrace()
    t.set_query_rewrite("who is bob?", "who is bob smith?")
    t.set_multi_queries(["q1", "q2", "q3"])
    t.add_dense("q1", [_doc("dense hit", page=2)])
    t.add_sparse("q1", [_doc("sparse hit")])
    t.set_fused([_doc("fused hit")])
    t.set_final_context("the context", {"max_context_chars": 8000})
    t.set_provider("Cerebras · gpt-oss-120b")
    t.add_timing("retrieval", 12.34)
    t.set_tokens({"prompt": 10, "completion": 5, "total": 15, "estimated": True})

    d = t.to_dict()
    assert d["original_query"] == "who is bob?"
    assert d["rewritten_query"] == "who is bob smith?"
    assert d["multi_queries"] == ["q1", "q2", "q3"]
    assert d["dense_by_query"][0]["query"] == "q1"
    assert d["dense_by_query"][0]["hits"][0]["location"] == "page 2"
    assert d["dense_by_query"][0]["hits"][0]["rank"] == 1
    assert d["sparse_by_query"][0]["hits"][0]["preview"] == "sparse hit"
    assert d["fused"][0]["source"] == "a.txt"
    assert d["final_context_chars"] == len("the context")
    assert d["provider"] == "Cerebras · gpt-oss-120b"
    assert d["timings_ms"]["retrieval"] == 12.3
    assert d["tokens"]["total"] == 15


def test_trace_reranked_flags_enabled():
    t = RetrievalTrace()
    assert t.to_dict()["rerank_enabled"] is False
    t.set_reranked([_doc("reranked")])
    assert t.to_dict()["rerank_enabled"] is True
    assert t.to_dict()["reranked"][0]["preview"] == "reranked"


def test_trace_preview_is_capped():
    t = RetrievalTrace()
    t.add_dense("q", [_doc("x" * (PREVIEW_CHARS + 500))])
    hit = t.to_dict()["dense_by_query"][0]["hits"][0]
    assert len(hit["preview"]) == PREVIEW_CHARS
    assert hit["chars"] == PREVIEW_CHARS + 500   # full length still reported


def test_trace_never_raises_on_bad_input():
    """Tracing is best-effort — a malformed doc must not propagate an error."""
    t = RetrievalTrace()
    t.add_dense("q", [object()])          # no page_content / metadata attrs
    t.set_final_context(None, None)       # None inputs
    # Nothing raised; the trace still serialises.
    assert isinstance(t.to_dict(), dict)


# ─────────────────────────────────────────────────────────────────────
# Token usage extraction / estimation
# ─────────────────────────────────────────────────────────────────────
def test_extract_usage_from_usage_metadata():
    msg = SimpleNamespace(
        usage_metadata={"input_tokens": 100, "output_tokens": 40, "total_tokens": 140}
    )
    u = extract_usage(msg)
    assert u == {"prompt": 100, "completion": 40, "total": 140, "estimated": False}


def test_extract_usage_from_response_metadata():
    msg = SimpleNamespace(
        usage_metadata=None,
        response_metadata={"token_usage": {"prompt_tokens": 7, "completion_tokens": 3}},
    )
    u = extract_usage(msg)
    assert u["prompt"] == 7 and u["completion"] == 3 and u["total"] == 10
    assert u["estimated"] is False


def test_extract_usage_returns_none_when_absent():
    assert extract_usage(SimpleNamespace()) is None
    assert extract_usage(SimpleNamespace(usage_metadata={}, response_metadata={})) is None


def test_estimate_tokens_roughly_four_chars_each():
    assert estimate_tokens("") == 0
    assert estimate_tokens("a" * 40) == 10
    assert estimate_tokens(None) == 0


# ─────────────────────────────────────────────────────────────────────
# Content-hash duplicate detection
# ─────────────────────────────────────────────────────────────────────
def test_content_hash_ignores_name_and_whitespace():
    a = content_hash(["hello   world", "second   chunk"])
    b = content_hash(["hello world", "second chunk"])       # different spacing
    assert a == b                                           # whitespace-normalised
    c = content_hash([("hello world", {}), ("second chunk", {})])  # tuple shape
    assert a == c
    assert a != content_hash(["totally different text"])


def test_find_duplicate_matches_by_content(tmp_path):
    vm = VectorStoreManager(index_path=str(tmp_path / "vs"))
    chash = content_hash(["shared content here"])
    vm.add_documents(["shared content here"], source_filename="original.txt",
                     content_hash=chash)

    # Same content, different name → detected as a duplicate of original.txt.
    assert vm.find_duplicate(chash) == "original.txt"
    # `ignore` skips the named file (re-indexing the same file isn't a self-dup).
    assert vm.find_duplicate(chash, ignore="original.txt") is None
    # Unknown content is not a duplicate.
    assert vm.find_duplicate(content_hash(["brand new"])) is None
    assert vm.find_duplicate("") is None


# ─────────────────────────────────────────────────────────────────────
# retrieval_inspector setting
# ─────────────────────────────────────────────────────────────────────
def test_retrieval_inspector_off_by_default(restore_settings):
    config.save_settings({"retrieval_inspector": False})
    assert config.retrieval_inspector_enabled() is False


def test_retrieval_inspector_on_when_truthy(restore_settings):
    for val in (True, "true", "on", "1", "yes"):
        config.save_settings({"retrieval_inspector": val})
        assert config.retrieval_inspector_enabled() is True


# ─────────────────────────────────────────────────────────────────────
# Request-metric telemetry (SQLite)
# ─────────────────────────────────────────────────────────────────────
def _metric(total_tokens=150, total_ms=900.0, provider="Cerebras · gpt-oss-120b"):
    return {
        "provider": provider,
        "tokens": {"prompt": 100, "completion": 50, "total": total_tokens,
                   "estimated": False},
        "retrieval_ms": 120.0,
        "generation_ms": 780.0,
        "total_ms": total_ms,
    }


def test_record_and_read_back_metric():
    storage.init_db()
    before = storage.metrics_summary()["requests"]
    storage.record_request_metric(_metric())
    summary = storage.metrics_summary()
    assert summary["requests"] == before + 1

    recent = storage.recent_metrics(limit=5)
    assert recent[0]["total_tokens"] == 150
    assert recent[0]["provider"] == "Cerebras · gpt-oss-120b"
    assert recent[0]["tokens_estimated"] == 0


def test_metrics_summary_averages():
    storage.init_db()
    # Two more requests with known values; averages should stay finite/rounded.
    storage.record_request_metric(_metric(total_tokens=100, total_ms=1000.0))
    storage.record_request_metric(_metric(total_tokens=300, total_ms=2000.0))
    s = storage.metrics_summary()
    assert s["requests"] >= 2
    assert s["avg_tokens"] > 0
    assert s["avg_total_ms"] > 0


def test_record_metric_never_raises_on_garbage():
    storage.init_db()
    # Missing 'tokens' key, wrong types — must be swallowed, not raised.
    storage.record_request_metric({"provider": None})
    storage.record_request_metric({})
