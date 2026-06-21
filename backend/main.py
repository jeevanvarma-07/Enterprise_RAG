from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from typing import List, Optional
import os
import json
import shutil
import asyncio

import config
from services import storage
from services.document_processing import process_document_chunks
from services.indexing import VectorStoreManager
from services.generation import RAGPipeline
from pydantic import BaseModel

app = FastAPI(title="Enterprise RAG API", version=config.APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Singletons
config.ensure_dirs()
storage.init_db()
vector_manager = VectorStoreManager(index_path=str(config.VECTOR_STORE_DIR))
rag_pipeline = RAGPipeline(vector_manager)


class ChatRequest(BaseModel):
    message: str
    model_name: Optional[str] = config.DEFAULT_MODEL
    provider: Optional[str] = None  # resolved from model_name if omitted
    chat_history: Optional[List[dict]] = []  # [{role: 'user'|'ai', content: str}]


# ─────────────────────────────────────────────
# Health / readiness
# ─────────────────────────────────────────────

@app.get("/")
async def root():
    """Friendly landing for a direct hit on the API root."""
    return {"name": "Enterprise RAG API", "version": config.APP_VERSION, "docs": "/docs"}


@app.get("/api/health")
async def health():
    """
    Lightweight readiness probe. The desktop shell (Tauri sidecar) polls this on
    startup to know when the backend is up; it also gives a one-glance status of
    the index, the active mode, and how many LLM providers are configured.
    Deliberately cheap — no model loading, no network.
    """
    from services.embeddings import signature as embedding_signature

    settings = config.get_settings()
    providers_ready = sum(1 for p in config.list_providers() if p["configured"])
    return {
        "status": "ok",
        "version": config.APP_VERSION,
        "mode": settings.get("mode", "lite"),
        "index_loaded": vector_manager.is_loaded(),
        "document_count": vector_manager.get_doc_count(),
        "providers_configured": providers_ready,
        "embedding": embedding_signature(),
    }


@app.get("/api/system")
async def system_info():
    """
    Detected hardware (RAM / CPU / GPU) + the suggested performance profile.
    Powers the Settings → Performance Mode panel's "Detected … Apply suggested"
    flow. Detection is best-effort and never raises (see services/system_info).
    """
    from services.system_info import detect_system

    return await asyncio.to_thread(detect_system)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

async def _process_one(file: UploadFile) -> dict:
    """Save a single uploaded file and index it. Returns status dict."""
    file_path = str(config.UPLOADS_DIR / file.filename)
    try:
        with open(file_path, "wb") as buf:
            shutil.copyfileobj(file.file, buf)
        chunks = process_document_chunks(file_path)
        if chunks:
            vector_manager.add_documents(chunks, source_filename=file.filename)
            return {"file": file.filename, "status": "ok", "chunks": len(chunks)}
        return {"file": file.filename, "status": "empty"}
    except Exception as e:
        return {"file": file.filename, "status": "error", "detail": str(e)}


# ─────────────────────────────────────────────
# Upload  (concurrent processing of 300 files)
# ─────────────────────────────────────────────

@app.post("/api/upload")
async def upload_documents(files: List[UploadFile] = File(...)):
    """
    Accept up to 300+ files. Each is processed concurrently via asyncio.gather
    so the total wall-clock time stays manageable even under heavy load.
    """
    tasks = [_process_one(f) for f in files]
    results = await asyncio.gather(*tasks)
    vector_manager.save_index()

    successful = [r for r in results if r["status"] == "ok"]
    errors = [r for r in results if r["status"] == "error"]

    return {
        "message": f"Processed {len(files)} file(s). "
                   f"{len(successful)} indexed, {len(errors)} failed.",
        "results": results,
    }


# ─────────────────────────────────────────────
# Chat
# ─────────────────────────────────────────────

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    try:
        answer, sources = rag_pipeline.generate_response(
            request.message,
            request.model_name,
            chat_history=request.chat_history,
            provider=request.provider,
        )
        return {"response": answer, "sources": sources}
    except ValueError as e:
        # Config problems (missing API key, unknown provider) — actionable 400.
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/stream")
async def chat_stream_endpoint(request: ChatRequest):
    """
    Server-Sent Events stream of the answer. Emits `sources` once, then many
    `token` events, then `done`. Errors (e.g. missing API key) arrive as an
    `error` event so the UI can show an actionable message inline.

    Starlette runs this sync generator in a threadpool, so the blocking LLM
    stream never stalls the event loop.
    """
    def event_gen():
        try:
            for event in rag_pipeline.generate_response_stream(
                request.message,
                request.model_name,
                chat_history=request.chat_history,
                provider=request.provider,
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except ValueError as e:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(e)})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(e)})}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─────────────────────────────────────────────
# Models & Settings
# ─────────────────────────────────────────────

@app.get("/api/models")
async def get_models():
    """
    All known models, each tagged with provider + an `available` flag.
    Includes any models from a locally-running Ollama (auto-detected).
    """
    from services.providers import detect_ollama

    models = config.list_models()

    # Fold in live Ollama models so users with Ollama installed get offline
    # options with zero configuration.
    ollama = detect_ollama()
    if ollama["running"]:
        for m in ollama["models"]:
            models.append({
                "provider": "ollama",
                "provider_label": config.PROVIDERS["ollama"]["label"],
                "available": True,
                **m,
            })

    return {
        "models": models,
        "default": config.DEFAULT_MODEL,
        "default_provider": config.DEFAULT_PROVIDER,
    }


@app.get("/api/providers")
async def get_providers():
    """
    Provider summary for the settings UI: which are configured, which need a
    key, plus live Ollama status. Never returns secrets.
    """
    from services.providers import detect_ollama

    providers = config.list_providers()
    ollama = detect_ollama()
    for p in providers:
        if p["name"] == "ollama":
            p["configured"] = ollama["running"]
            p["model_count"] = len(ollama["models"])
    return {"providers": providers, "ollama_running": ollama["running"]}


@app.get("/api/settings")
async def get_settings():
    """
    Return persisted, non-secret user preferences, plus a few resolved/derived
    flags the settings UI needs (the effective rerank state and whether the
    optional reranker package is installed).
    """
    from services.reranker import is_available as rerank_available

    return {
        **config.get_settings(),
        "rerank_enabled": config.rerank_enabled(),
        "rerank_available": rerank_available(),
        # Resolved (clamped) retrieval knobs actually in force — lets the UI
        # show the effective values even if settings.json holds a raw/odd one.
        "retrieval_effective": config.retrieval_params(),
    }


class SettingsUpdate(BaseModel):
    mode: Optional[str] = None
    active_provider: Optional[str] = None
    active_model: Optional[str] = None
    embedding_backend: Optional[str] = None   # sentence-transformers | fastembed
    embedding_model: Optional[str] = None
    rerank: Optional[str] = None          # auto | on | off  (cross-encoder reranking)
    ocr: Optional[str] = None             # auto | on | off  (scanned-PDF / image OCR)
    # Retrieval tuning (all optional; clamped server-side in retrieval_params)
    top_k: Optional[int] = None
    fetch_k: Optional[int] = None
    mmr_lambda: Optional[float] = None
    bm25_k: Optional[int] = None
    final_k: Optional[int] = None
    rerank_candidates: Optional[int] = None


@app.post("/api/settings")
async def update_settings(update: SettingsUpdate):
    """Merge provided fields into persisted settings."""
    values = {k: v for k, v in update.dict().items() if v is not None}
    return config.save_settings(values)


# ─────────────────────────────────────────────
# Chat sessions & history (SQLite-backed)
# ─────────────────────────────────────────────

class SessionCreate(BaseModel):
    title: Optional[str] = None


class SessionRename(BaseModel):
    title: str


class MessageCreate(BaseModel):
    role: str                       # 'user' | 'ai'
    content: str
    sources: Optional[List[dict]] = None


@app.get("/api/sessions")
async def get_sessions():
    """List all saved chat sessions, most recent first."""
    return {"sessions": storage.list_sessions()}


@app.post("/api/sessions")
async def create_session(body: SessionCreate):
    """Create a new chat session."""
    return storage.create_session(body.title)


@app.get("/api/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    """Return the full message history for a session."""
    return {"messages": storage.get_messages(session_id)}


@app.post("/api/sessions/{session_id}/messages")
async def add_session_message(session_id: str, body: MessageCreate):
    """Append a message to a session's history."""
    ok = storage.add_message(session_id, body.role, body.content, body.sources)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"ok": True}


@app.patch("/api/sessions/{session_id}")
async def patch_session(session_id: str, body: SessionRename):
    """Rename a session."""
    if not storage.rename_session(session_id, body.title):
        raise HTTPException(status_code=404, detail="Session not found or empty title.")
    return {"ok": True}


@app.delete("/api/sessions/{session_id}")
async def remove_session(session_id: str):
    """Delete a session and all its messages."""
    if not storage.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"ok": True}


# ─────────────────────────────────────────────
# Data Sources management
# ─────────────────────────────────────────────

@app.get("/api/sources")
async def list_sources():
    """List all raw uploaded files in the uploads/ directory with metadata."""
    uploads_dir = str(config.UPLOADS_DIR)
    os.makedirs(uploads_dir, exist_ok=True)
    files = []
    total_bytes = 0
    for fname in os.listdir(uploads_dir):
        fpath = os.path.join(uploads_dir, fname)
        if os.path.isfile(fpath):
            size = os.path.getsize(fpath)
            total_bytes += size
            ext = os.path.splitext(fname)[-1].lower().lstrip(".")
            files.append({
                "filename": fname,
                "size_bytes": size,
                "type": ext,
                "modified": os.path.getmtime(fpath),
            })
    files.sort(key=lambda f: f["modified"], reverse=True)
    return {"files": files, "total_bytes": total_bytes, "count": len(files)}


class ScrapeRequest(BaseModel):
    url: str

@app.post("/api/sources/scrape")
async def scrape_url(request: ScrapeRequest):
    """Fetch a webpage, extract its text, and index it into the vector store."""
    try:
        import urllib.request
        from html.parser import HTMLParser

        class TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.text_parts = []
                self._skip = False
            def handle_starttag(self, tag, attrs):
                if tag in ("script", "style", "nav", "footer"):
                    self._skip = True
            def handle_endtag(self, tag):
                if tag in ("script", "style", "nav", "footer"):
                    self._skip = False
            def handle_data(self, data):
                if not self._skip and data.strip():
                    self.text_parts.append(data.strip())

        req = urllib.request.Request(
            request.url,
            headers={"User-Agent": "Mozilla/5.0 (Enterprise RAG scraper)"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        parser = TextExtractor()
        parser.feed(html)
        text = "\n".join(parser.text_parts)

        if len(text.strip()) < 100:
            raise HTTPException(status_code=422, detail="Could not extract meaningful text from this URL.")

        from services.document_processing import chunk_text
        chunks = chunk_text(text)

        # Use the URL domain as source label
        from urllib.parse import urlparse
        label = urlparse(request.url).netloc + urlparse(request.url).path
        label = label[:80]  # keep it short

        vector_manager.add_documents(chunks, source_filename=label)
        vector_manager.save_index()

        return {"message": f"Indexed {len(chunks)} chunks from {label}", "chunks": len(chunks), "source": label}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




# ─────────────────────────────────────────────
# Index / Vector Store management
# ─────────────────────────────────────────────

@app.get("/api/index/status")
async def index_status():
    return {
        "is_loaded": vector_manager.is_loaded(),
        "document_count": vector_manager.get_doc_count(),
    }


@app.get("/api/index/documents")
async def list_documents():
    """Return all indexed files with chunk count and timestamp."""
    return {"documents": vector_manager.list_documents()}


@app.delete("/api/index/documents/{filename:path}")
async def delete_document(filename: str):
    """Delete a specific file's chunks from the FAISS index."""
    success = vector_manager.delete_by_source(filename)
    if not success:
        raise HTTPException(status_code=404, detail=f"'{filename}' not found in index.")
    return {"message": f"'{filename}' removed from index."}


class BatchDeleteRequest(BaseModel):
    filenames: List[str]

@app.post("/api/index/documents/batch-delete")
async def batch_delete_documents(request: BatchDeleteRequest):
    """Delete multiple files from the index in one call (parallelized)."""
    results = []
    for filename in request.filenames:
        ok = vector_manager.delete_by_source(filename)
        results.append({"filename": filename, "deleted": ok})
    vector_manager.save_index()
    deleted = sum(1 for r in results if r["deleted"])
    return {"message": f"Deleted {deleted}/{len(request.filenames)} files.", "results": results}


@app.delete("/api/index/clear")
async def clear_index():
    vector_manager.clear()
    return {"message": "Index cleared successfully"}


@app.post("/api/index/rebuild")
async def rebuild_index():
    """
    Re-embed all indexed documents with the current embedding backend/model.

    Use this after switching embeddings (e.g. to the torch-free `fastembed`
    backend) — chunk text and citations are preserved, only the vectors are
    recomputed. Runs in a worker thread so the (potentially long) re-embed of a
    large index doesn't block the event loop / other requests.
    """
    result = await asyncio.to_thread(vector_manager.rebuild_embeddings)
    if not result.get("rebuilt"):
        return {"message": "Nothing to rebuild — the index is empty.", **result}
    return {
        "message": f"Re-embedded {result['documents']} chunks with "
                   f"'{result['signature']}'.",
        **result,
    }


@app.get("/api/index/export")
async def export_index():
    """
    Zip and return the FAISS vector store directory for download / backup.
    """
    index_path = str(config.VECTOR_STORE_DIR)
    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="No index found to export.")

    zip_path = str(config.DATA_DIR / "vector_store_export")
    shutil.make_archive(zip_path, "zip", index_path)
    return FileResponse(
        zip_path + ".zip",
        media_type="application/zip",
        filename="vector_store.zip",
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)
