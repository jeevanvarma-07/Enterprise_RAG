"""Tests for the retrieval evaluation harness (scripts/eval_retrieval.py).

These build a tiny real FAISS index from the synthetic corpus, so they load the
embedding model — slower, but they exercise the true retrieval path. Reranking
is intentionally excluded (no model download in the test suite).
"""

import config
from services.indexing import VectorStoreManager
from scripts.eval_retrieval import (
    SYNTHETIC_DATASET,
    SYNTHETIC_DOCS,
    _first_hit_rank,
    evaluate,
    run_suite,
)
from langchain_core.documents import Document


def _store(tmp_path):
    vm = VectorStoreManager(index_path=str(tmp_path / "vs"))
    vm.add_documents(SYNTHETIC_DOCS, source_filename="synthetic.txt")
    return vm


def test_first_hit_rank_pure():
    docs = [Document(page_content="nothing here"), Document(page_content="answer: Paris")]
    assert _first_hit_rank(docs, ["paris"]) == 2          # case-insensitive, 1-based
    assert _first_hit_rank(docs, ["tokyo"]) == 0          # miss
    assert _first_hit_rank([], ["paris"]) == 0            # empty


def test_evaluate_single_query(tmp_path):
    vm = _store(tmp_path)
    m = evaluate(
        vm,
        [{"query": "Where is the Eiffel Tower?", "expects": ["Paris"]}],
        config.retrieval_params(),
    )
    assert m["n"] == 1
    assert m["recall"] == 1.0
    assert m["per_query"][0]["hit"] is True
    assert 0.0 < m["mrr"] <= 1.0


def test_suite_hybrid_not_worse_than_dense(tmp_path):
    vm = _store(tmp_path)
    res = run_suite(vm, SYNTHETIC_DATASET, include_rerank=False)
    assert set(res) == {"dense-only", "hybrid"}            # rerank excluded by default
    # Hybrid (dense + BM25) should never lose to dense-only on this set.
    assert res["hybrid"]["recall"] >= res["dense-only"]["recall"]
    assert res["hybrid"]["recall"] >= 0.8
    for m in res.values():
        assert 0.0 <= m["mrr"] <= 1.0
