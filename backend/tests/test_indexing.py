"""
Tests for VectorStoreManager: metadata merging, backward-compat add_documents,
deletion, and BM25. These build a real (tiny) FAISS index in a temp dir, so
they load the embedding model — slower, but they exercise the true path.
"""

import pytest

from services.indexing import VectorStoreManager


@pytest.fixture()
def vm(tmp_path):
    return VectorStoreManager(index_path=str(tmp_path / "vs"))


def test_add_plain_strings_backward_compatible(vm):
    vm.add_documents(["hello world", "another chunk"], source_filename="a.txt")
    docs = vm.get_documents()
    assert len(docs) == 2
    assert all(d.metadata["source"] == "a.txt" for d in docs)
    # plain strings -> no location metadata
    assert all("page" not in d.metadata and "rows" not in d.metadata for d in docs)


def test_add_tuples_merges_location_metadata(vm):
    vm.add_documents(
        [("page one text", {"page": 1}), ("rows text", {"rows": "1-15"})],
        source_filename="b.pdf",
    )
    metas = {tuple(sorted(d.metadata.items())) for d in vm.get_documents()}
    assert ("page", 1) in {kv for m in metas for kv in m}
    assert ("rows", "1-15") in {kv for m in metas for kv in m}


def test_metadata_count_recorded(vm):
    vm.add_documents(["x", "y", "z"], source_filename="c.txt")
    listing = {d["filename"]: d["chunks"] for d in vm.list_documents()}
    assert listing["c.txt"] == 3


def test_delete_by_source_removes_only_that_file(vm):
    vm.add_documents(["keep1", "keep2"], source_filename="keep.txt")
    vm.add_documents(["drop1"], source_filename="drop.txt")
    assert vm.delete_by_source("drop.txt") is True
    remaining = {d.metadata["source"] for d in vm.get_documents()}
    assert remaining == {"keep.txt"}
    assert vm.delete_by_source("missing.txt") is False


def test_bm25_retriever_returns_results(vm):
    vm.add_documents(
        ["the quick brown fox", "lazy dogs sleep", "fox runs fast"],
        source_filename="d.txt",
    )
    bm25 = vm.bm25_retriever(k=2)
    assert bm25 is not None
    hits = bm25.invoke("fox")
    assert any("fox" in h.page_content for h in hits)
