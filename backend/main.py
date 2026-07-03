from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from typing import List, Optional
import os
import json
import shutil
import asyncio

import logging

import config
from fastapi.concurrency import run_in_threadpool
from services import storage
from services import evaluation
from services.logging_config import setup_logging
from services.document_processing import process_document_chunks, content_hash
from services.indexing import VectorStoreManager
from services.generation import RAGPipeline
from pydantic import BaseModel

# Configure logging before anything else so startup messages are captured.
setup_logging()
logger = logging.getLogger(__name__)

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
    # Sanitize the client-supplied filename: strip any directory components so a
    # crafted name like "../../settings.json" cannot escape UPLOADS_DIR.
    safe_name = os.path.basename(file.filename or "")
    if not safe_name or safe_name in (".", ".."):
        return {"file": file.filename, "status": "error", "detail": "invalid filename"}
    file_path = str(config.UPLOADS_DIR / safe_name)
    try:
        with open(file_path, "wb") as buf:
            shutil.copyfileobj(file.file, buf)
        chunks = process_document_chunks(file_path)
        if not chunks:
            return {"file": safe_name, "status": "empty"}
        # Fingerprint the extracted content and skip re-indexing a document whose
        # text is already in the store (e.g. the same file uploaded under a new
        # name) — keeps the index clean and retrieval free of duplicate chunks.
        chash = content_hash(chunks)
        dup = vector_manager.find_duplicate(chash, ignore=safe_name)
        if dup:
            return {"file": safe_name, "status": "duplicate",
                    "detail": f"identical content already indexed as '{dup}'"}
        vector_manager.add_documents(chunks, source_filename=safe_name, content_hash=chash)
        return {"file": safe_name, "status": "ok", "chunks": len(chunks)}
    except Exception as e:
        return {"file": safe_name, "status": "error", "detail": str(e)}


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
    duplicates = [r for r in results if r["status"] == "duplicate"]
    errors = [r for r in results if r["status"] == "error"]

    return {
        "message": f"Processed {len(files)} file(s). "
                   f"{len(successful)} indexed, {len(duplicates)} duplicate(s) skipped, "
                   f"{len(errors)} failed.",
        "results": results,
    }


# ─────────────────────────────────────────────
# Chat
# ─────────────────────────────────────────────

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    try:
        answer, sources, notice = rag_pipeline.generate_response(
            request.message,
            request.model_name,
            chat_history=request.chat_history,
            provider=request.provider,
        )
        resp = {"response": answer, "sources": sources}
        if notice:
            resp["notice"] = notice          # set only when a provider fallback happened
        return resp
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

    When the (default-off) Retrieval Inspector setting is on, the stream also
    carries one `inspection` event with the full pipeline trace. The `done` event
    always carries per-request `metrics` (tokens + latency), which we persist for
    the performance dashboard as it arrives.
    """
    inspect = config.retrieval_inspector_enabled()

    def event_gen():
        try:
            for event in rag_pipeline.generate_response_stream(
                request.message,
                request.model_name,
                chat_history=request.chat_history,
                provider=request.provider,
                inspect=inspect,
            ):
                if event.get("type") == "done" and event.get("metrics"):
                    storage.record_request_metric(event["metrics"])
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
# Metrics  (per-request telemetry for the performance dashboard)
# ─────────────────────────────────────────────

@app.get("/api/metrics/summary")
async def metrics_summary_endpoint():
    """Aggregate token/latency telemetry (counts + averages) for header cards."""
    return storage.metrics_summary()


@app.get("/api/metrics/recent")
async def metrics_recent_endpoint(limit: int = 50):
    """Most-recent per-request telemetry rows, newest first, for trend charts."""
    return {"metrics": storage.recent_metrics(limit=limit)}


# ─────────────────────────────────────────────
# Evaluation  (RAGAS answer-quality metrics for the Evaluation Dashboard)
# ─────────────────────────────────────────────

class EvalRunRequest(BaseModel):
    question: str
    ground_truth: Optional[str] = None   # labelled answer → enables context_recall
    # Optional pre-supplied answer/contexts; when omitted the live pipeline runs.
    answer: Optional[str] = None
    contexts: Optional[List[str]] = None


class EvalDatasetItem(BaseModel):
    question: str
    ground_truth: Optional[str] = None


class EvalDatasetRequest(BaseModel):
    items: List[EvalDatasetItem]


# Cap a single dataset run so a huge upload can't hammer a free-tier provider's
# rate limit (e.g. Groq's 6k TPM). Larger sets should be split across runs.
_MAX_DATASET_ITEMS = 25


@app.post("/api/eval/run")
async def eval_run_endpoint(body: EvalRunRequest):
    """
    Evaluate ONE answer. If `answer`/`contexts` are omitted, the live RAG
    pipeline produces them from `question`. Runs in a threadpool because the
    LLM-judge calls are blocking. Result is persisted and returned.
    """
    try:
        result = await run_in_threadpool(
            evaluation.evaluate,
            body.question,
            answer=body.answer,
            contexts=body.contexts,
            ground_truth=body.ground_truth,
        )
        result["id"] = storage.record_eval_run(result)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/eval/dataset")
async def eval_dataset_endpoint(body: EvalDatasetRequest):
    """
    Evaluate a labelled dataset sequentially (concurrency 1, to respect free-tier
    rate limits) and return per-item results + an aggregate. Each item that
    carries a ground_truth also gets context_recall.
    """
    items = body.items[:_MAX_DATASET_ITEMS]
    if not items:
        raise HTTPException(status_code=400, detail="No dataset items provided.")

    def _run_all():
        rows = []
        for it in items:
            r = evaluation.evaluate(it.question, ground_truth=it.ground_truth)
            r["id"] = storage.record_eval_run(r)
            rows.append(r)
        return rows

    try:
        rows = await run_in_threadpool(_run_all)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Aggregate the non-null scores per metric.
    def _avg(key: str) -> Optional[float]:
        vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
        return round(sum(vals) / len(vals), 3) if vals else None

    aggregate = {
        "count": len(rows),
        "truncated": len(body.items) > _MAX_DATASET_ITEMS,
        "avg_faithfulness": _avg("faithfulness"),
        "avg_answer_relevancy": _avg("answer_relevancy"),
        "avg_context_precision": _avg("context_precision"),
        "avg_context_recall": _avg("context_recall"),
    }
    return {"aggregate": aggregate, "results": rows}


@app.get("/api/eval/summary")
async def eval_summary_endpoint():
    """Aggregate RAGAS metrics (count + per-metric averages) for header cards."""
    return storage.eval_summary()


@app.get("/api/eval/recent")
async def eval_recent_endpoint(limit: int = 50):
    """Most-recent evaluation runs, newest first, for the dashboard list."""
    return {"runs": storage.recent_evals(limit=limit)}


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

    # Prefer the user's persisted choice (active_model) as the default, so the
    # picker reopens on the last model they used across restarts. Fall back to
    # the hardcoded default only if the saved model is no longer offered.
    settings = config.get_settings()
    saved_model = settings.get("active_model")
    known_ids = {m.get("id") for m in models}
    if saved_model in known_ids:
        default_model = saved_model
        default_provider = settings.get("active_provider") or config.provider_for_model(saved_model)
    else:
        default_model = config.DEFAULT_MODEL
        default_provider = config.DEFAULT_PROVIDER

    return {
        "models": models,
        "default": default_model,
        "default_provider": default_provider,
    }


@app.get("/api/providers")
async def get_providers():
    """
    Provider summary for the settings UI: which are configured, which need a
    key, whether a key is held in the encrypted in-app store, plus live Ollama
    status. Never returns secrets.
    """
    from services.providers import detect_ollama
    from services import keystore

    providers = config.list_providers()
    stored = set(keystore.configured_providers())
    ollama = detect_ollama()
    for p in providers:
        p["has_stored_key"] = p["name"] in stored
        if p["name"] == "ollama":
            p["configured"] = ollama["running"]
            p["model_count"] = len(ollama["models"])
    return {
        "providers": providers,
        "ollama_running": ollama["running"],
        "key_storage_available": keystore.available(),
    }


@app.get("/api/embeddings/models")
async def get_embedding_models():
    """
    The selectable embedding models for the Settings picker (shares config's
    single registry so the UI and backend never drift). Includes the multilingual
    options (Tamil + 50 languages) and flags the one currently active.
    """
    return {"models": config.list_embedding_models()}


class ProviderKey(BaseModel):
    api_key: str


@app.post("/api/providers/{name}/key")
async def set_provider_key(name: str, body: ProviderKey):
    """
    Store an API key for a provider in the encrypted in-app key store.
    The key is written encrypted-at-rest to the per-user data dir, never to the
    repo or a plaintext file. An empty value clears the stored key.
    """
    from services import keystore

    cfg = config.PROVIDERS.get(name)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{name}'.")
    if not cfg.get("api_key_env"):
        raise HTTPException(status_code=400, detail=f"Provider '{name}' does not use an API key.")
    if not keystore.available():
        raise HTTPException(
            status_code=503,
            detail="Encrypted key storage is unavailable (cryptography not installed).",
        )

    keystore.set_key(name, body.api_key)
    return {"name": name, "configured": config.provider_is_configured(name)}


@app.delete("/api/providers/{name}/key")
async def delete_provider_key(name: str):
    """Remove any stored key for a provider from the encrypted in-app store."""
    from services import keystore

    if name not in config.PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{name}'.")
    keystore.delete_key(name)
    return {"name": name, "configured": config.provider_is_configured(name)}


@app.get("/api/settings")
async def get_settings():
    """
    Return persisted, non-secret user preferences, plus a few resolved/derived
    flags the settings UI needs (the effective rerank state and whether the
    optional reranker package is installed).
    """
    from services.reranker import is_available as rerank_available
    from services import table_extraction

    return {
        **config.get_settings(),
        "rerank_enabled": config.rerank_enabled(),
        "rerank_available": rerank_available(),
        # Resolved (clamped) retrieval knobs actually in force — lets the UI
        # show the effective values even if settings.json holds a raw/odd one.
        "retrieval_effective": config.retrieval_params(),
        # Resolved prompt-size budget actually in force.
        "prompt_budget": config.prompt_budget(),
        # Resolved table engine + which engines are actually installed, so the UI
        # can show the effective parser and disable the docling option on Lite.
        "table_engine_effective": config.table_engine(),
        "pdfplumber_available": table_extraction.PDFPLUMBER_AVAILABLE,
        "docling_available": table_extraction._docling_importable(),
    }


class SettingsUpdate(BaseModel):
    onboarded: Optional[bool] = None      # first-run wizard completed
    mode: Optional[str] = None
    active_provider: Optional[str] = None
    active_model: Optional[str] = None
    embedding_backend: Optional[str] = None   # sentence-transformers | fastembed
    embedding_model: Optional[str] = None
    rerank: Optional[str] = None          # auto | on | off  (cross-encoder reranking)
    ocr: Optional[str] = None             # auto | on | off  (scanned-PDF / image OCR)
    table_engine: Optional[str] = None    # auto | pdfplumber | docling | off (PDF tables)
    llm_fallback: Optional[bool] = None   # auto-retry with another configured provider
    # Prompt-size budget (clamped server-side in prompt_budget) — keeps requests
    # under a provider's tokens-per-minute limit.
    history_turns: Optional[int] = None
    context_chars: Optional[int] = None
    # Retrieval tuning (all optional; clamped server-side in retrieval_params)
    top_k: Optional[int] = None
    fetch_k: Optional[int] = None
    mmr_lambda: Optional[float] = None
    bm25_k: Optional[int] = None
    final_k: Optional[int] = None
    rerank_candidates: Optional[int] = None
    # Evaluation — which LLM judges answer quality (defaults to the chat provider/model)
    eval_provider: Optional[str] = None
    eval_model: Optional[str] = None


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

        # Skip re-indexing a page whose text is already in the store.
        chash = content_hash(chunks)
        dup = vector_manager.find_duplicate(chash, ignore=label)
        if dup:
            return {"message": f"Skipped — identical content already indexed as '{dup}'.",
                    "chunks": 0, "source": label, "duplicate": dup}

        vector_manager.add_documents(chunks, source_filename=label, content_hash=chash)
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
