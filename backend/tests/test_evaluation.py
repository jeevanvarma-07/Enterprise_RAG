"""
Tests for the hand-rolled RAGAS evaluation layer (services/evaluation.py) and
its SQLite persistence (storage.eval_runs).

All offline: the LLM judge and the embeddings model are monkeypatched with
deterministic stubs, so no network / no keys / no model download. Storage runs
against the throwaway RAG_DATA_DIR that conftest isolates.
"""

import json

import pytest

from services import evaluation, storage


# ─────────────────────────────────────────────────────────────────────
# Stubs — a scripted judge and a toy embedder
# ─────────────────────────────────────────────────────────────────────
class _ScriptedJudge:
    """Returns canned JSON strings in call order; usage is a fixed token count."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, prompt, provider, model, max_tokens=1024):
        self.calls.append(prompt)
        reply = self.replies.pop(0) if self.replies else None
        usage = {"prompt": 5, "completion": 5, "total": 10} if reply is not None else None
        return reply, usage


class _ToyEmbeddings:
    """A tiny deterministic embedder: hashes words into a fixed-size bag vector."""

    _DIM = 16

    def embed_query(self, text):
        vec = [0.0] * self._DIM
        for w in (text or "").lower().split():
            vec[hash(w) % self._DIM] += 1.0
        return vec


# ─────────────────────────────────────────────────────────────────────
# _parse_json / _yes / _cosine helpers
# ─────────────────────────────────────────────────────────────────────
def test_parse_json_handles_fences_and_prose():
    assert evaluation._parse_json('```json\n[true, false]\n```') == [True, False]
    assert evaluation._parse_json('Sure! Here: {"a": 1} done') == {"a": 1}
    assert evaluation._parse_json("not json at all") is None
    assert evaluation._parse_json(None) is None


def test_yes_verdict_variants():
    for truthy in (True, 1, "yes", "true", "Supported", "relevant"):
        assert evaluation._yes(truthy) is True
    for falsy in (False, 0, "no", "false", ""):
        assert evaluation._yes(falsy) is False


def test_cosine_bounds():
    assert evaluation._cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert evaluation._cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert evaluation._cosine([], [1]) == 0.0


# ─────────────────────────────────────────────────────────────────────
# Faithfulness
# ─────────────────────────────────────────────────────────────────────
def test_faithfulness_fraction_supported(monkeypatch):
    # claim-extraction returns 2 claims; verdicts mark 1 of 2 supported.
    judge = _ScriptedJudge(['["claim a", "claim b"]', "[true, false]"])
    monkeypatch.setattr(evaluation, "_judge", judge)
    out = evaluation.faithfulness("some answer", ["ctx"], provider="p", model="m")
    assert out["score"] == pytest.approx(0.5)
    assert out["detail"]["supported"] == 1 and out["detail"]["total"] == 2


def test_faithfulness_judge_unavailable_is_none(monkeypatch):
    monkeypatch.setattr(evaluation, "_judge", _ScriptedJudge([None, None]))
    out = evaluation.faithfulness("a", ["ctx"], provider="p", model="m")
    assert out["score"] is None


def test_faithfulness_no_context_is_none(monkeypatch):
    out = evaluation.faithfulness("a", [], provider="p", model="m")
    assert out["score"] is None


# ─────────────────────────────────────────────────────────────────────
# Answer relevancy
# ─────────────────────────────────────────────────────────────────────
def test_answer_relevancy_uses_embeddings(monkeypatch):
    monkeypatch.setattr(evaluation, "_judge",
                        _ScriptedJudge(['["where is the tower", "tower location"]']))
    monkeypatch.setattr(evaluation, "_get_embeddings", lambda: _ToyEmbeddings())
    out = evaluation.answer_relevancy("where is the tower", "in paris",
                                      provider="p", model="m")
    assert out["score"] is not None and 0.0 <= out["score"] <= 1.0
    assert len(out["detail"]["generated"]) == 2


def test_answer_relevancy_noncommittal_is_zero(monkeypatch):
    # Should short-circuit to 0 without ever calling the judge.
    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        return None, None

    monkeypatch.setattr(evaluation, "_judge", _boom)
    out = evaluation.answer_relevancy("q?", "I don't know", provider="p", model="m")
    assert out["score"] == 0.0
    assert called["n"] == 0


# ─────────────────────────────────────────────────────────────────────
# Context precision — rank-weighted
# ─────────────────────────────────────────────────────────────────────
def test_context_precision_rank_weighted(monkeypatch):
    # relevant, irrelevant, relevant → precision@1=1, precision@3=2/3;
    # mean over relevant ranks = (1 + 2/3) / 2 = 0.8333
    monkeypatch.setattr(evaluation, "_judge", _ScriptedJudge(["[true, false, true]"]))
    out = evaluation.context_precision("q", ["c1", "c2", "c3"], provider="p", model="m")
    assert out["score"] == pytest.approx((1.0 + 2.0 / 3.0) / 2.0, abs=1e-3)


def test_context_precision_all_irrelevant_is_zero(monkeypatch):
    monkeypatch.setattr(evaluation, "_judge", _ScriptedJudge(["[false, false]"]))
    out = evaluation.context_precision("q", ["c1", "c2"], provider="p", model="m")
    assert out["score"] == 0.0


# ─────────────────────────────────────────────────────────────────────
# Context recall — needs ground truth
# ─────────────────────────────────────────────────────────────────────
def test_context_recall_fraction_attributed(monkeypatch):
    monkeypatch.setattr(evaluation, "_judge", _ScriptedJudge(["[true, true, false]"]))
    out = evaluation.context_recall("the reference answer", ["ctx"],
                                    provider="p", model="m")
    assert out["score"] == pytest.approx(2.0 / 3.0)


def test_context_recall_without_ground_truth_is_none(monkeypatch):
    out = evaluation.context_recall("", ["ctx"], provider="p", model="m")
    assert out["score"] is None


# ─────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────
def test_evaluate_end_to_end_with_supplied_answer(monkeypatch):
    # Enough scripted replies for: faithfulness(2), relevancy(1),
    # precision(1), recall(1).
    judge = _ScriptedJudge([
        '["c1", "c2"]', "[true, true]",     # faithfulness → 1.0
        '["gen q"]',                         # relevancy → generated questions
        "[true, true]",                      # precision → 1.0
        "[true]",                            # recall → 1.0
    ])
    monkeypatch.setattr(evaluation, "_judge", judge)
    monkeypatch.setattr(evaluation, "_get_embeddings", lambda: _ToyEmbeddings())

    res = evaluation.evaluate(
        "where is the tower?",
        answer="It is in Paris.",
        contexts=["The tower is in Paris."],
        ground_truth="The tower is in Paris.",
        provider="p", model="m",
    )
    assert res["faithfulness"] == pytest.approx(1.0)
    assert res["context_precision"] == pytest.approx(1.0)
    assert res["context_recall"] == pytest.approx(1.0)
    assert res["answer_relevancy"] is not None
    assert res["eval_tokens"] > 0
    assert res["eval_provider"] == "p"


def test_evaluate_never_raises_on_dead_judge(monkeypatch):
    # A judge that always fails → all metrics None, no exception.
    monkeypatch.setattr(evaluation, "_judge", lambda *a, **k: (None, None))
    monkeypatch.setattr(evaluation, "_get_embeddings", lambda: _ToyEmbeddings())
    res = evaluation.evaluate("q?", answer="a", contexts=["c"], provider="p", model="m")
    assert res["faithfulness"] is None
    assert res["context_precision"] is None


# ─────────────────────────────────────────────────────────────────────
# Storage round-trip
# ─────────────────────────────────────────────────────────────────────
def test_eval_run_persists_and_reads_back():
    storage.init_db()
    row_id = storage.record_eval_run({
        "question": "q1",
        "answer": "a1",
        "contexts": ["c1", "c2"],
        "ground_truth": "gt",
        "faithfulness": 0.8,
        "answer_relevancy": 0.9,
        "context_precision": 1.0,
        "context_recall": 0.5,
        "eval_provider": "p",
        "eval_model": "m",
        "eval_tokens": 42,
        "eval_latency_ms": 123.4,
    })
    assert row_id is not None

    recent = storage.recent_evals(limit=5)
    assert recent and recent[0]["question"] == "q1"
    assert recent[0]["faithfulness"] == 0.8

    summary = storage.eval_summary()
    assert summary["runs"] >= 1
    assert summary["avg_faithfulness"] is not None


def test_eval_summary_averages_only_nonnull():
    storage.init_db()
    # Two runs; context_recall is null on one — average must ignore the null.
    storage.record_eval_run({"question": "qa", "faithfulness": 1.0,
                             "context_recall": None})
    storage.record_eval_run({"question": "qb", "faithfulness": 0.0,
                             "context_recall": 0.4})
    s = storage.eval_summary()
    assert s["runs"] >= 2
    # avg_context_recall should reflect only the non-null value(s), never crash.
    assert s["avg_context_recall"] is not None
