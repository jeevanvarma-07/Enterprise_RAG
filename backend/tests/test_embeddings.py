"""Tests for the embedding backend abstraction + index provenance stamping."""

import json
import os

import config
from services import embeddings
from services.indexing import VectorStoreManager


def test_signature_default(restore_settings):
    config.save_settings({"embedding_backend": "sentence-transformers",
                          "embedding_model": "all-MiniLM-L6-v2"})
    assert embeddings.signature() == "sentence-transformers:all-MiniLM-L6-v2"


def test_signature_reflects_settings(restore_settings):
    config.save_settings({"embedding_backend": "fastembed", "embedding_model": "all-MiniLM-L6-v2"})
    assert embeddings.signature() == "fastembed:all-MiniLM-L6-v2"


def test_get_embeddings_is_usable():
    # Default backend must always produce a real, query-able embedder.
    emb = embeddings.get_embeddings()
    vec = emb.embed_query("hello world")
    assert isinstance(vec, list) and len(vec) > 0


def test_fastembed_name_mapping():
    assert embeddings._fastembed_name("all-MiniLM-L6-v2") == "sentence-transformers/all-MiniLM-L6-v2"
    assert embeddings._fastembed_name("custom-model") == "custom-model"  # passthrough


# ── Multilingual models (Feature 1) ──────────────────────────────────

def test_fastembed_name_multilingual_mappings():
    # The two paraphrase models live under the sentence-transformers/ namespace
    # in fastembed's catalog; the e5 id is already fully-qualified (passthrough).
    assert (embeddings._fastembed_name("paraphrase-multilingual-MiniLM-L12-v2")
            == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    assert (embeddings._fastembed_name("paraphrase-multilingual-mpnet-base-v2")
            == "sentence-transformers/paraphrase-multilingual-mpnet-base-v2")
    assert (embeddings._fastembed_name("intfloat/multilingual-e5-large")
            == "intfloat/multilingual-e5-large")


def test_signature_multilingual(restore_settings):
    config.save_settings({"embedding_backend": "fastembed",
                          "embedding_model": "paraphrase-multilingual-MiniLM-L12-v2"})
    assert embeddings.signature() == "fastembed:paraphrase-multilingual-MiniLM-L12-v2"


def test_list_embedding_models_shape(restore_settings):
    config.save_settings({"embedding_model": "paraphrase-multilingual-MiniLM-L12-v2"})
    models = config.list_embedding_models()
    assert len(models) == len(config.EMBEDDING_MODELS)
    ids = [m["id"] for m in models]
    assert "all-MiniLM-L6-v2" in ids
    assert "paraphrase-multilingual-MiniLM-L12-v2" in ids
    assert "intfloat/multilingual-e5-large" in ids
    # Required keys for the UI picker are present on every entry.
    for m in models:
        for key in ("id", "label", "languages", "dim", "multilingual", "tier", "active"):
            assert key in m, f"{key} missing from {m['id']}"
    # Exactly the selected model is flagged active.
    active = [m["id"] for m in models if m["active"]]
    assert active == ["paraphrase-multilingual-MiniLM-L12-v2"]


def test_e5_is_registered_for_prefix():
    # The e5 model must be in the prefix set or its retrieval silently degrades.
    assert "intfloat/multilingual-e5-large" in config.E5_PREFIX_MODELS


def test_e5_prefix_wrapper_prepends_instructions():
    # Deterministic, no model download: a stub inner records what it received.
    class _Stub:
        def embed_documents(self, texts):
            return texts
        def embed_query(self, text):
            return text

    wrapped = embeddings._E5PrefixEmbeddings(_Stub())
    assert wrapped.embed_documents(["chunk one"]) == ["passage: chunk one"]
    assert wrapped.embed_query("a question") == "query: a question"


def test_index_writes_embedding_sidecar(tmp_path):
    vm = VectorStoreManager(index_path=str(tmp_path / "vs"))
    vm.add_documents(["hello", "world"], source_filename="a.txt")
    vm.save_index()   # persistence point — also stamps provenance
    sidecar = os.path.join(str(tmp_path / "vs"), "embedding_info.json")
    assert os.path.exists(sidecar)
    with open(sidecar) as f:
        assert json.load(f)["signature"] == embeddings.signature()


def test_rebuild_embeddings_preserves_docs(tmp_path):
    vm = VectorStoreManager(index_path=str(tmp_path / "vs"))
    vm.add_documents(["alpha beta gamma", "delta epsilon zeta"], source_filename="a.txt")
    vm.save_index()
    before = vm.get_doc_count()

    result = vm.rebuild_embeddings()
    assert result["rebuilt"] is True
    assert result["documents"] == before
    assert vm.get_doc_count() == before          # same number of vectors
    assert vm.as_retriever() is not None          # still queryable

    sidecar = os.path.join(str(tmp_path / "vs"), "embedding_info.json")
    with open(sidecar) as f:
        assert json.load(f)["signature"] == embeddings.signature()


def test_rebuild_embeddings_preserves_metadata(tmp_path):
    # Citation metadata (page/rows) and the source label must survive a rebuild.
    vm = VectorStoreManager(index_path=str(tmp_path / "vs"))
    vm.add_documents([("page one text", {"page": 1})], source_filename="doc.pdf")
    vm.save_index()
    vm.rebuild_embeddings()
    docs = vm.get_documents()
    assert any(d.metadata.get("page") == 1 and d.metadata.get("source") == "doc.pdf"
               for d in docs)


def test_rebuild_embeddings_empty_is_noop(tmp_path):
    vm = VectorStoreManager(index_path=str(tmp_path / "vs"))
    result = vm.rebuild_embeddings()
    assert result["rebuilt"] is False
    assert result["documents"] == 0


def test_mismatch_warning_does_not_raise(tmp_path, capsys):
    vs_dir = tmp_path / "vs"
    vm = VectorStoreManager(index_path=str(vs_dir))
    vm.add_documents(["hello"], source_filename="a.txt")
    vm.save_index()
    # Corrupt the provenance to simulate an index built by a different backend.
    with open(os.path.join(str(vs_dir), "embedding_info.json"), "w") as f:
        json.dump({"signature": "other-backend:other-model"}, f)
    # Reloading must warn, not crash.
    vm2 = VectorStoreManager(index_path=str(vs_dir))
    assert vm2.is_loaded()
    assert "WARNING" in capsys.readouterr().out
