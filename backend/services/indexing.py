from __future__ import annotations

import logging
import os
import json
import shutil
from datetime import datetime
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

import config
from services.embeddings import get_embeddings, signature as embedding_signature

logger = logging.getLogger(__name__)


class VectorStoreManager:
    def __init__(self, index_path: str | None = None):
        self.index_path = index_path or str(config.VECTOR_STORE_DIR)
        self.metadata_path = os.path.join(self.index_path, "metadata.json")
        # Records which embedding backend+model built this index, so we can warn
        # if it's later loaded under a different one (vectors wouldn't match).
        self.embedding_info_path = os.path.join(self.index_path, "embedding_info.json")
        self.embeddings = get_embeddings()
        self.vector_store = None
        self._bm25 = None           # cached BM25 keyword retriever (hybrid search)
        self._metadata: dict = {}   # {filename: {chunks, timestamp}}
        self._load_metadata()
        self.load_index()

    # ---------- embedding provenance ----------

    def _write_embedding_info(self):
        """Stamp the active embedding signature next to the index."""
        try:
            os.makedirs(self.index_path, exist_ok=True)
            with open(self.embedding_info_path, "w") as f:
                json.dump({"signature": embedding_signature()}, f)
        except OSError:
            pass  # provenance is advisory; never block indexing on it

    def _check_embedding_info(self):
        """Warn (don't fail) if the index was built with different embeddings."""
        if not os.path.exists(self.embedding_info_path):
            return  # legacy index: provenance unknown, stay quiet
        try:
            with open(self.embedding_info_path, "r") as f:
                have = json.load(f).get("signature")
        except (OSError, json.JSONDecodeError):
            return
        want = embedding_signature()
        if have and have != want:
            logger.warning(f"Index was built with embeddings '{have}' "
                           f"but the active backend is '{want}'. Retrieval may be wrong — "
                           f"rebuild the index after changing embeddings.")

    # ---------- metadata helpers ----------

    def _load_metadata(self):
        if os.path.exists(self.metadata_path):
            with open(self.metadata_path, "r") as f:
                self._metadata = json.load(f)
        else:
            self._metadata = {}

    def _save_metadata(self):
        os.makedirs(self.index_path, exist_ok=True)
        with open(self.metadata_path, "w") as f:
            json.dump(self._metadata, f, indent=2)

    # ---------- core FAISS ops ----------

    def load_index(self):
        faiss_file = os.path.join(self.index_path, "index.faiss")
        if os.path.exists(faiss_file):
            self.vector_store = FAISS.load_local(
                self.index_path, self.embeddings, allow_dangerous_deserialization=True
            )
            self._check_embedding_info()
            logger.info("Loaded existing FAISS index.")
        else:
            logger.info("No existing index found. Starting fresh.")

    def add_documents(self, text_chunks: list, source_filename: str = "unknown"):
        """
        Add chunks to FAISS and record metadata.

        `text_chunks` may be either a list of plain strings, or a list of
        (text, meta) pairs where `meta` carries location info (e.g. page/rows).
        Any such meta is merged into the chunk's Document metadata so citations
        can point at where in the source the text came from.
        """
        documents = []
        for chunk in text_chunks:
            if isinstance(chunk, (tuple, list)) and len(chunk) == 2 and isinstance(chunk[1], dict):
                text, extra = chunk[0], chunk[1]
            else:
                text, extra = chunk, {}
            documents.append(
                Document(page_content=text, metadata={"source": source_filename, **extra})
            )
        if self.vector_store is None:
            self.vector_store = FAISS.from_documents(documents, self.embeddings)
        else:
            self.vector_store.add_documents(documents)

        # Update metadata
        self._metadata[source_filename] = {
            "chunks": len(text_chunks),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._save_metadata()
        self._bm25 = None   # docs changed → rebuild keyword index lazily

    def save_index(self):
        if self.vector_store:
            self.vector_store.save_local(self.index_path)
            self._write_embedding_info()   # stamp provenance alongside the index

    def rebuild_embeddings(self) -> dict:
        """
        Re-embed every currently-indexed chunk with the active embedding backend.

        This is the migration path for switching embeddings (e.g. moving Lite mode
        off torch onto the ONNX `fastembed` backend): vectors from different models
        aren't comparable, so the index must be rebuilt. We re-embed the existing
        `Document` objects rather than re-reading source files, which means chunk
        text, citation metadata (page/rows), AND URL-scraped sources (that live
        only in the index, not on disk) all survive unchanged — only the vectors
        are recomputed.

        Atomic: the new index is built into a temp dir and its files are swapped
        in only on success, so a failure mid-rebuild leaves the existing index
        intact. `metadata.json` is untouched (same sources, same chunk counts).
        """
        docs = self.get_documents()
        if not docs:
            return {"rebuilt": False, "reason": "empty", "documents": 0}

        # The backend may have changed in settings since construction — rebuild it.
        self.embeddings = get_embeddings()
        new_store = FAISS.from_documents(docs, self.embeddings)

        # Build into a temp dir, then move the FAISS files into place.
        tmp_path = self.index_path + ".rebuild"
        if os.path.exists(tmp_path):
            shutil.rmtree(tmp_path, ignore_errors=True)
        os.makedirs(tmp_path, exist_ok=True)
        new_store.save_local(tmp_path)

        os.makedirs(self.index_path, exist_ok=True)
        for fname in ("index.faiss", "index.pkl"):
            src = os.path.join(tmp_path, fname)
            if os.path.exists(src):
                shutil.move(src, os.path.join(self.index_path, fname))
        shutil.rmtree(tmp_path, ignore_errors=True)

        self.vector_store = new_store
        self._bm25 = None               # docs re-embedded → rebuild keyword index lazily
        self._write_embedding_info()    # stamp the new signature
        return {"rebuilt": True, "documents": len(docs), "signature": embedding_signature()}

    def as_retriever(self, search_kwargs=None):
        if self.vector_store is None:
            return None
        if search_kwargs is None:
            # MMR: Maximum Marginal Relevance — diverse AND relevant results
            search_kwargs = {"k": 5, "fetch_k": 20, "lambda_mult": 0.6}
        return self.vector_store.as_retriever(
            search_type="mmr",
            search_kwargs=search_kwargs,
        )

    def is_loaded(self):
        return self.vector_store is not None

    # ---------- hybrid search: BM25 keyword retrieval ----------

    def get_documents(self) -> list:
        """All Document objects currently in the store (for BM25 / inspection)."""
        if self.vector_store is None:
            return []
        return list(self.vector_store.docstore._dict.values())

    def bm25_retriever(self, k: int = 6):
        """
        Lazily build (and cache) a BM25 keyword retriever over the indexed docs.

        Sparse keyword matching catches exact terms that dense embeddings miss
        (names, codes, rare words). Returns None if there are no docs or the
        optional `rank_bm25` backend isn't installed — callers degrade to
        dense-only retrieval, so the Lite path never breaks.
        """
        docs = self.get_documents()
        if not docs:
            return None
        if self._bm25 is None:
            try:
                from langchain_community.retrievers import BM25Retriever
                self._bm25 = BM25Retriever.from_documents(docs)
            except Exception as e:
                logger.warning(f"BM25 keyword retriever unavailable: {e}")
                return None
        self._bm25.k = k
        return self._bm25

    def get_doc_count(self):
        if self.vector_store:
            return self.vector_store.index.ntotal
        return 0

    def clear(self):
        self.vector_store = None
        self._bm25 = None
        self._metadata = {}
        if os.path.exists(self.index_path):
            shutil.rmtree(self.index_path)
        logger.info("Vector store cleared.")

    # ---------- Phase 2: management ----------

    def list_documents(self) -> list:
        """Return list of all indexed files with metadata."""
        return [
            {"filename": fname, "chunks": meta["chunks"], "timestamp": meta["timestamp"]}
            for fname, meta in self._metadata.items()
        ]

    def delete_by_source(self, filename: str) -> bool:
        """
        Delete all chunks belonging to `filename` from FAISS and metadata.
        Rebuilds the index from remaining docs.
        """
        if not self.vector_store or filename not in self._metadata:
            return False

        # Collect all docs except those from this file
        all_docs = list(self.vector_store.docstore._dict.values())
        remaining = [d for d in all_docs if d.metadata.get("source") != filename]

        # Rebuild
        self.vector_store = None
        if remaining:
            self.vector_store = FAISS.from_documents(remaining, self.embeddings)
            self.save_index()
        else:
            if os.path.exists(self.index_path):
                shutil.rmtree(self.index_path)

        del self._metadata[filename]
        self._save_metadata()
        self._bm25 = None   # docs changed → rebuild keyword index lazily
        return True
