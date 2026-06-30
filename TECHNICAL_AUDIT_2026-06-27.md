# Enterprise RAG — Technical Audit (2026-06-27)

**Auditor perspective:** Senior engineer at Anthropic/OpenAI/Microsoft evaluating a student's 5th-semester portfolio project aiming for "enterprise-grade" quality.

**Codebase:** ~5,100 lines backend (Python/FastAPI), ~3,400 frontend (React 19/TS/Tailwind/Tauri), 101 backend tests, 0 frontend tests. Local-first RAG desktop app (Windows installers shipped; Linux deferred). Solo student dev building with AI assistants.

---

## Executive Summary

**Overall Grade: 6.5/10** — A genuinely impressive student project with several production-minded design decisions (streaming correctness, graceful provider fallback, encrypted key storage, honest loading/error states, behavioral tests) that put it above typical coursework. The RAG pipeline is correctly implemented and the architecture is sound. **Held back from "enterprise-grade" by systemic gaps**: zero observability (no logging, no crash reporting, no way to debug field issues), zero frontend tests, universal accessibility failures (no focus traps, no ARIA, no reduced-motion), no LICENSE file, and several concrete bugs (path traversal in upload, XSS-adjacent link injection risk, race conditions in chat, stream abort leaks).

**Strengths that stand out:**
- The RAG core (multi-query + RRF + MMR + exact CSV lookup + reranking + prompt budget) is **correctly implemented** and well-tested.
- Provider fallback with error classification + streaming mid-failure recovery is mature and unusual for a student project.
- Backend tests assert real behavioral contracts (e.g. `test_prompt_budget.py:139` measures injected context length against baseline), not just "doesn't crash."
- SSE streaming consumer (`ChatInterface.tsx:254-291`) is the single best piece of frontend code — handles partial frames, stale closures, and network vs server errors correctly.
- Fernet-encrypted keystore is real security (not security theater), tested, with graceful crypto-unavailable degradation.
- First-run wizard, honest connection status, progress feedback, citation modals, markdown export — real product thinking.

**Critical gaps (enterprise blockers):**
1. **No structured logging** — 18 `print()` in `document_processing.py`, 0 `import logging`. No log file, no request IDs. Cannot diagnose a user's issue.
2. **No LICENSE file** — legally all-rights-reserved despite "free/open-source" claims.
3. **Path traversal** — `main.py:92` writes `file.filename` with no sanitization (`../../settings.json` escapes uploads/).
4. **Zero frontend tests** — 3,400 lines of UI logic untested (no Vitest/Jest/Playwright).
5. **Systemic accessibility failures** — no focus traps in modals, no `aria-label` on icon buttons, no `prefers-reduced-motion`, inconsistent Escape handling.
6. **No error boundaries** in React — an uncaught error in one component crashes the whole app.
7. **No auto-update, no crash reporting** — versioning is manually triple-maintained and already drifted (`package.json` stuck at `0.0.0`).

---

## Scores by Dimension

| Dimension | Score | Justification |
|-----------|-------|---------------|
| **Architecture** | **7/10** | Clean service decomposition, sensible Lite/Power split, paths/settings abstracted correctly. Docked for: `config.py` at 696 lines (mild god module — registries belong in separate files), flat `providers.py` instead of `services/providers/` (acknowledged tech debt), and no module boundaries between embeddings/reranker (both mutate a shared FAISS index with no locking). |
| **RAG Pipeline** | **7.5/10** | Multi-query, RRF, MMR, exact-lookup, reranking, and prompt-budget are all correctly implemented with tests. History-aware rewrite works. Docked for: no semantic/contextual chunking (fixed 1000-char naive split), no query routing, no metadata filtering, and retrieval isn't citation-aware (page-level citations can span multiple chunks, so "page 3" might be wrong if only one chunk from that page was retrieved). |
| **Retrieval Quality** | **7/10** | Hybrid (FAISS + BM25) + RRF + reranking is solid. Table extraction as labelled rows is smart. Embedding provenance tracking is mature. Docked for: naive chunking (no semantic boundaries, tables/prose mixed), MMR `lambda=0.6` is aggressive (may sacrifice recall for diversity), and BM25 caching is lazy but never invalidates on delete (`:110` sets `_bm25 = None` on add, but not on `delete_by_source` — **bug**). |
| **Generation Quality** | **6.5/10** | Prompt budget correctly caps context. Exact-lookup guarantees ID questions work. Streaming + fallback is excellent. Docked for: system prompt is static (no query routing, no persona), prompt-budget trims history *and* context together (`:360-367` counts both against one limit, so a long history starves retrieval context), and no few-shot examples or chain-of-thought for complex questions. |
| **UI/UX** | **6/10** | Visually clean, loading/empty/error states everywhere, streaming feedback, honest status, source citations, first-run wizard. Feels above student-tier. **Docked heavily for accessibility**: no focus traps, no ARIA on icon buttons, no reduced-motion, native `alert()`/`confirm()` (`:128, :208`) break visual language, and the "4th Semester Project" footer (`:574`) breaks the enterprise illusion. No light theme (tokens defined but unused). |
| **Security** | **5/10** | **Critical:** path traversal (`main.py:92` — `file.filename` unsanitized). **High:** XSS-adjacent (react-markdown doesn't sanitize link `href`, so `[click](javascript:...)` from a malicious doc works). **Medium:** CORS is localhost + tauri origins (correct for local-first), but API has no auth — any local process can hit it. **Medium:** `.env` has a real Groq key (gitignored, but should be rotated). Fernet keystore is good. SQL injection impossible (parameterized queries, `:79, :114`). Error messages don't leak secrets. |
| **Scalability** | **5/10** | Breaks at: many docs (`delete_by_source` is O(n) rebuild, `:226-250`), concurrent deletes (FAISS write races — no locking), large files (blocking file I/O in upload, though `asyncio.gather` mitigates), settings.json corruption (read/write races under load). ThreadPoolExecutor correctly wraps sync embedding/rerank. In-memory BM25 + FAISS fine for <10k docs. Not designed for multi-tenancy. |
| **Performance** | **6/10** | Lite/Power split is the right move. 138MB frozen app is respectable. fastembed avoids torch. Lazy imports correct. Docked for: one-file PyInstaller re-extracts on every cold start (~3-5s unpacking cost), fixed 60s health probe with no graceful UI on timeout, first-run 90MB model download not masked by splash, and advertised OCR/local-LLM silently no-op in the shipped binary (Tesseract/llama.cpp not bundled). |
| **Code Quality** | **6/10** | Backend is clean: good comments, small functions, section banners, behavioral tests. Frontend has bright spots (SSE consumer, stale-closure awareness) but: `SettingsModal` 706 lines, `ChatInterface` 505 lines (god components), duplicated types across files, bare axios with copy-pasted error extraction, index-based message keys (`:442` — causes flicker on reorder), unguarded `res.data.documents` (`:353` — crashes on 500), and concrete bugs (rapid-send race, un-aborted stream leak). |
| **Maintainability** | **4.5/10** | No tests = cannot refactor safely. No error boundary. Duplicated interfaces. Stale docs (README says React 18, plan has hardcoded constants drifted from real settings). Comments are unusually good. A new engineer could *read* it but not extend it confidently. Backend is better (tests + clear boundaries); frontend is ad-hoc. |
| **Enterprise Readiness** | **4/10** | **Hard blockers:** no structured logging/log file, no crash reporting, no way to diagnose field issues, no LICENSE, no auto-update, drifted versions. **Credit for:** encrypted keys, no secrets in repo, per-user data isolation, real CI, graceful provider fallback. This is a solid *prototype's* ops story, not production. |

**Weighted Overall: 6.5/10** (RAG/architecture/backend stronger; ops/frontend weaker)

---

## Detailed Findings

### 1. RAG Pipeline (generation.py:564 lines)

#### Strengths
- **Multi-query is correctly implemented** (`:183-204`): LLM generates 3 variations via `.with_structured_output(QueryVariations)`, then retrieves for each and fuses with RRF. Pydantic validation ensures structured output.
- **RRF fusion is textbook** (`:89-104`): `score[doc] += 1/(rank + k)`, k=60, dedup by `page_content[:200]`. No off-by-one.
- **Exact CSV/ID lookup** (`:24-59`): scans every uploaded CSV/Excel for rows where any column exactly matches a numeric token from the query. Prepended to context so ID questions always work — clever and tested (`test_generation.py`).
- **Prompt budget** (`:353-381`): caps context + exact-match block together so total stays under `context_chars` (default 6000 ~ 1.5k tokens). Tested at `:test_prompt_budget.py:139` (measures injected length vs empty-template baseline). Fixed the real 413 "Request too large" bug on Groq.
- **Streaming + provider fallback** (`:476-563`): tries candidates in order, announces fallback mid-stream, classifies errors (401→auth, 429→rate-limit, timeout→offline), yields `{type: "notice"|"token"|"error"|"done"}`. Handles mid-stream failures (`:552` — can't restart cleanly, yields error and returns). Sentinel `_STREAM_EMPTY` (`:21`) distinguishes "provider never started" from "returned empty string."
- **History-aware rewrite** (`:155-181`): uses a separate LLM call to rewrite follow-ups into standalone questions before multi-query. Contextualize prompt is well-designed (`:144-150`).
- **MMR retrieval** (`:205-235`): each query variation uses `max_marginal_relevance_search(k=5, fetch_k=20, lambda_mult=0.6)` for diversity. Works.

#### Weaknesses & Bugs
- **Prompt budget starves retrieval when history is long** (`:360-367`). `_estimate_token_usage` counts history + system + context together against one `context_chars` limit. If history is 4k chars, context gets capped to 2k → only ~2 retrieved chunks fit. A long conversation gradually loses grounding. **Fix:** separate budgets for history (tail-truncate old turns) and context (keep retrieval full).
- **BM25 cache not invalidated on delete** — `indexing.py:110` sets `_bm25 = None` on `add_documents`, but `:249` (`delete_by_source`) doesn't. So after deleting a doc, keyword search still sees its chunks until the next add. **Bug.**
- **No citation-aware retrieval.** Page-level citations (`{"page": 3}`) can span multiple chunks. If only one chunk from page 3 is retrieved, the citation still says "page 3" — but the LLM only saw that one chunk, not the whole page. User clicks the source and sees a fuller page than the model had.
- **No semantic chunking.** Fixed 1000-char split (`document_processing.py:337-343`) with 150-char overlap. Cuts mid-sentence, mixes table rows with prose. State-of-the-art uses sentence/paragraph boundaries + embedding-based similarity to find natural breakpoints.
- **No query routing.** All questions get the same system prompt and retrieval. No routing to specialized prompts (e.g. comparison questions, summarization, numerical reasoning).
- **No metadata filtering.** Can't ask "only PDFs" or "docs from last week" — every query searches the whole index.
- **MMR lambda=0.6 is aggressive** — prioritizes diversity over relevance. May hurt recall for focused questions. Should be tunable or query-adaptive.

#### Missing Features (vs SOTA RAG)
- Contextual/agentic retrieval (each chunk gets context from surrounding chunks or doc structure)
- Query decomposition (break complex multi-hop questions into sub-queries)
- Hypothetical document embeddings (HyDE — embed the question's ideal answer, not the question itself)
- Self-reflection / answer verification (model critiques its own answer before returning)
- Incremental index updates (add/delete without O(n) rebuild)

---

### 2. Retrieval Quality (indexing.py:250 lines, document_processing.py:343 lines)

#### Strengths
- **Hybrid search is correctly fused** (`:163-192`): FAISS dense + BM25 keyword, RRF-merged in `generation.py`. Both retrievers use the same `k`. BM25 is cached (`:23, :197-202`) and lazy-built on first use.
- **Table extraction is smart** (`table_extraction.py:192 lines`): extracts tables *as tables* (each row becomes `Col: val | Col: val`, tagged `content_type:"table"`), not mangled plaintext. Two engines: `pdfplumber` (default, pure-Python, Lite-safe) and Docling/TableFormer (Power opt-in, skips on Py<3.10/no torch). Fully defensive — degrades to PyPDF2 text, never blocks upload (`:116-127`). **This is unusually mature.**
- **Embedding provenance tracking** (`:28-52`): `embedding_info.json` stamps the backend+model signature next to the index; warns (doesn't fail) on mismatch when loaded. Prevents silent retrieval degradation after switching embeddings.
- **Rebuild is atomic** (`:117-160`): builds new index into a temp dir, swaps files only on success. Old index stays intact if rebuild crashes. Preserves chunk text + citations (doesn't re-read files). URL-scraped sources (that live only in the index, not on disk) survive.
- **Citation metadata correct** (`document_processing.py:85-113`): `(text, {"page": N})` for PDFs, `(text, {"rows": "16-30", "sheet": "Sales"})` for Excel. Merged into `Document.metadata` at index time (`:96-98`).

#### Weaknesses & Bugs
- **BM25 cache bug (already noted):** `:indexing.py:110` clears `_bm25` on add, but `:249` doesn't on delete. Keyword search returns stale results until next add.
- **O(n) delete** (`:226-250`): `delete_by_source` rebuilds the entire FAISS index from `remaining` docs. Fine for <100 docs; unacceptable for 10k. LanceDB/Chroma have true delete. Or keep a deletion tombstone set and filter results.
- **No deduplication.** Uploading the same PDF twice indexes it twice. No content hash or filename check.
- **Chunking is naive** (`document_processing.py:337-343`): fixed 1000 chars, 150 overlap, `RecursiveCharacterTextSplitter` with default separators. Cuts mid-sentence. Tables (already extracted separately) still go through this splitter, so a large table row might be split across chunks → harder to retrieve.
- **No chunk size tuning by content type.** Prose might want 1000 chars; code/logs want smaller; tables want whole-row chunks. One-size-fits-all.
- **No embedding choice rationale.** `all-MiniLM-L6-v2` (default) is 384d, asymmetric (trained on sentence pairs). For long-document RAG, a symmetric model or a passage-specialized one (e.g. `e5-large`) might retrieve better. No eval comparing them.
- **MMR params not validated.** `lambda_mult=0.6` (`:generation.py:228`) is hardcoded. No experiment showing this beats 0.5 or 0.7.

#### Missing Features
- Incremental index updates (add/delete without full rebuild)
- Semantic chunking (sentence/paragraph boundaries, embedding-similarity-based merges)
- Chunk context injection (prepend "This chunk is from Section 3.2: Model Architecture" to help retrieval)
- Parent/child chunks (index small chunks, retrieve their larger parent context)
- Metadata filtering (filter by doc type, date, or user-defined tags before search)

---

### 3. Security (main.py:597 lines, keystore.py:174 lines)

#### Critical
- **Path traversal in upload** (`main.py:92`):
  ```python
  file_path = str(config.UPLOADS_DIR / file.filename)
  ```
  No `os.path.basename()` or sanitization. A filename like `../../settings.json` writes outside `uploads/`. Mitigated by being local single-user, but textbook flaw. **Fix:** `file.filename = secure_filename(file.filename)` (werkzeug) or `os.path.basename`.

#### High
- **XSS-adjacent in markdown rendering** (`ChatInterface.tsx:449`): AI answers render through `ReactMarkdown` + `remarkGfm`. React-markdown v10 **does not render raw HTML by default** (good), but **link `href`s are not sanitized**. A malicious/compromised document could make the model output `[click](javascript:alert(1))`. React-markdown mitigates `javascript:` URIs by default, but no explicit `rehype-sanitize` or URL-scheme allowlist. **Fix:** add `rehype-sanitize` or allowlist `http`/`https`.

#### Medium
- **No auth on the API** — FastAPI binds to `127.0.0.1:8000` (`:main.py:73`), so only localhost can hit it. Correct for a local-first desktop app. But any local process (malicious browser tab, other app) can upload/delete docs, read chat history. For "enterprise" multi-user, need per-user auth or OS-level sandboxing.
- **Real Groq key in plaintext `.env`** — gitignored (confirmed), but the key should be rotated (plan Phase 0 says so). Anyone with disk/backup/screenshot access when `.env` was visible has the key.
- **CORS origins are permissive** (`:19-25`): allows `localhost:5173/5174/3000`, `tauri://localhost`, `http://tauri.localhost`. Correct for dev + Tauri. No wildcard, no public origin.

#### Low / Good
- **Fernet keystore is real security** (`keystore.py`): AES-128-CBC + HMAC, keys encrypted at rest, master key in `DATA_DIR/secret.key` with `chmod 0o600` (`:81`). Gracefully degrades if `cryptography` absent (`:35-41`). Threat model is clear (`:10-14`): protects against casual exposure, not an attacker with home-dir access. **Well-designed.**
- **SQL injection impossible** (`storage.py`): all queries parameterized (`:79, :114, :152`). No string interpolation into SQL.
- **Error messages don't leak secrets** — provider fallback yields "The selected model failed (missing API key)" (`:generation.py:531`), not the key itself. Good.
- **Settings.json is JSON, not YAML/TOML** — no RCE via `yaml.unsafe_load`. Corruption degrades gracefully (`:config.py:683-686` — catches `JSONDecodeError`, falls back to defaults).

#### Recommendations
1. `os.path.basename(file.filename)` in upload (`:main.py:92`) — **critical fix, 1 line**
2. Add `rehype-sanitize` to `ReactMarkdown` (`:ChatInterface.tsx:449`)
3. Rotate the `.env` Groq key and delete it from disk; use the encrypted keystore
4. (Later) OS keyring integration or user passphrase for keystore (current threat model is fine for v1)

---

### 4. Backend Architecture & API Design (main.py:597 lines, config.py:697 lines)

#### Strengths
- **Service decomposition is clean** — `document_processing`, `indexing`, `generation`, `providers`, `embeddings`, `reranker`, `keystore`, `storage`, `system_info` are separate modules with clear boundaries. `main.py` is a thin orchestration layer.
- **Settings system is sound** (`config.py:679-696`): JSON-persisted, defaults in `DEFAULT_SETTINGS` (`:503-515`), merged on read (`:680-687`), validated/coerced by resolvers (`active_mode`, `rerank_enabled`, `:628-676`). Corruption degrades gracefully.
- **Path abstraction correct** (`:36-67`): everything resolves from `DATA_DIR`, which is `RAG_DATA_DIR` env (packaged app) or `backend/` (dev). No hardcoded `C:\`. `pathlib` everywhere.
- **CORS config is runtime** (`:85-89`): driven by `RAG_CORS_ORIGINS` env, not hardcoded. Tauri sets its origin at startup.
- **Async concurrency correct** (`main.py:108-126`): upload uses `asyncio.gather` to process 300 files concurrently. Embedding/rerank use `asyncio.to_thread` to wrap sync work (`:83, :567`). No blocking I/O in the event loop (except the file write at `:92-95`, which is brief).
- **Health endpoint is lightweight** (`:51-71`): no model loading, no network. Just index/settings/provider counts. Tauri polls this every 500ms during startup probe.

#### Weaknesses
- **`config.py` at 697 lines is a mild god module** — holds path defs, `PROVIDERS` registry (`:110-245`), `EMBEDDING_MODELS` (`:265-296`), `MODE_PROFILES` (`:484-501`), settings I/O, and 15+ resolver functions. It's well-sectioned with header comments and navigable, but the data registries belong in separate files (`providers.json`, `models.py`).
- **`providers.py` is flat** (226 lines in one file) — plan acknowledges this (`CLAUDE.md:136`). Should be `services/providers/{factory,groq,openai,ollama,llamacpp,fallback}.py`. Minor tech debt, doesn't block anything.
- **No request validation with Pydantic** — `ChatRequest` (`:34-38`) is a BaseModel, but upload/delete endpoints accept raw `List[UploadFile]` / body with no validation. Any malformed input crashes with a raw 500.
- **No concurrency safety on FAISS writes** — `vector_manager.add_documents` and `.delete_by_source` both mutate the same in-memory FAISS index with no lock. Concurrent upload + delete can corrupt the index. `storage.py` uses per-call connections (safe), but `indexing.py` is a singleton (`:main.py:30`).
- **No structured logging** — 18 `print()` in `document_processing.py`, 5 in `indexing.py`. No `import logging` anywhere. No log file, no request IDs, no log levels. Tauri drains stdout to a hidden console. **Cannot diagnose a field issue.**
- **Error handling is inconsistent** — some endpoints return `{"error": ...}` 200s (`:main.py:149`), others raise `HTTPException` (`:248, :584`). No global exception handler.

#### API Design Issues
- **Blocking file write in upload** (`:92-95`): `shutil.copyfileobj` is sync I/O. Should use `aiofiles` or `await file.file.read()` + `Path.write_bytes` in a thread.
- **No rate limiting** — a local attacker (malicious browser tab) can spam upload/delete.
- **No multipart size limit enforced** — relies on uvicorn's default. A 10GB file upload won't be rejected until the disk fills.

#### Missing (Enterprise)
- Structured logging (stdlib `logging` + rotating file handler)
- Request IDs (middleware that injects a UUID into every log line)
- OpenTelemetry / metrics (request latency, error rates, index size)
- Health endpoint should return 503 (not 200) if backend is degraded (e.g. no providers configured, index missing)

---

### 5. Frontend (3,431 lines TS/TSX)

*Full findings from the successful agent audit — summarized here for space.*

#### Strengths (UI/UX: 6/10, Code Quality: 5.5/10)
- **SSE streaming is correct** (`ChatInterface.tsx:254-291`): buffers partial frames, handles `decoder.decode({stream: true})`, distinguishes network/server errors, cleans up reader. **Best frontend code.**
- **Stale-closure awareness** (`:167-168, :185,203`): `sessionIdRef` + `justCreatedRef` + `cancelled` flags avoid async bugs.
- **Loading/empty/error states everywhere** — `VectorStoreTab`, `DataSourcesTab`, `App.tsx` all have spinners, empty illustrations, error messages.
- **Honest connection status** (`useHealth.ts` + `ConnectionStatus.tsx`): real `/api/health` poll, last-good state preserved in ref, hover tooltip, click-to-reprobe.
- **Progress feedback strong** — upload shows batched bar + "processing console" with per-file verdicts (`:UploadSection.tsx:74-88,134-182`).

#### Critical Bugs
- **Race condition on rapid send** (`ChatInterface.tsx:401`): example-query buttons call `handleSend` but **aren't disabled** during streaming. Clicking two quickly fires concurrent streams that both `patchLastMessage` the same bubble, corrupting output. **Fix:** disable examples while `loading`.
- **No AbortController** (`:231`): switching sessions mid-stream leaves the old reader running. It writes into the new session's last message. **Fix:** wrap fetch in `AbortController`, abort on session change.
- **XSS-adjacent** (`:449`): `ReactMarkdown` doesn't sanitize link `href` (covered in Security).
- **Index-based message keys** (`:442`): `key={idx}` causes flicker on reorder. **Fix:** `key={msg.id || idx}`.

#### Accessibility Failures (systemic, dragging UI/UX down to 6/10)
- **No focus traps in any modal** — `SettingsModal`, `HelpModal`, `SourceModal`, `FirstRunWizard` never trap Tab focus. Keyboard users Tab out into the page behind. None set `role="dialog"` / `aria-modal="true"`.
- **Escape closes inconsistently** — `SourceModal`/`HelpModal` handle Escape, `SettingsModal`/`FirstRunWizard` don't.
- **Icon buttons lack `aria-label`** — refresh/clear/export (`:380-387`), rename/delete (`:SessionsPanel.tsx:121`), help/settings (`:App.tsx:239-252`). Rely on `title` (not accessible to all AT).
- **No `prefers-reduced-motion`** — heavy Framer Motion everywhere, no respect for motion sensitivity.
- **Drag-drop doesn't actually drag** — `UploadSection.tsx:118` is a file input overlay, no `onDrop`. Label says "Drag & Drop" but only click works.

#### Missing
- **Zero frontend tests** — no `*.test.*` under `frontend/src`, no Vitest/Jest config.
- **No error boundary** — an uncaught error in one component crashes the whole app.
- **No i18n** — all strings hardcoded English.
- **God components** — `SettingsModal` 706 lines, `ChatInterface` 505 lines.
- **No light theme** — tokens defined (`index.css:3-12`) but unused; everything is hardcoded `slate-*` dark.

---

### 6. Engineering & Ops (tests, CI, packaging)

*Full findings from the successful agent audit — summarized.*

#### Strengths (Code Quality: 6/10, Enterprise Readiness: 4/10)
- **Backend tests are genuinely behavioral** (101 tests, 14 files): `test_prompt_budget.py:139` measures injected context length, `test_provider_fallback.py` covers streaming + mid-stream failure + error classification, `test_embeddings.py:133` corrupts provenance and asserts a warning. **Not shallow.**
- **Test isolation correct** (`conftest.py:14`): `RAG_DATA_DIR` set to tempdir before `import config`. No hardcoded paths, no flaky tests.
- **Dependency pinning is intelligent** (`requirements.txt:13`): pins LangChain `>=0.3,<0.4` with a comment explaining why.
- **Tauri shell is mature** (`lib.rs`): free-port selection, health probe, PyInstaller grandchild-orphan handling (`taskkill /T` by PID), backend teardown on `CloseRequested` + `ExitRequested`.
- **CI has real value** (`.github/workflows/backend-tests.yml`, `desktop-build.yml`): runs tests on Py3.9+3.11, builds Win+Linux installers on tags. Path-filtered, HF cache.

#### Critical Gaps (dragging Enterprise Readiness to 4/10)
- **No structured logging** — `print()` is the entire strategy. No log file, no request IDs, cannot debug field issues.
- **No LICENSE file** — repo is legally all-rights-reserved despite "free/open-source" claims.
- **Path traversal in upload** (covered in Security).
- **Zero frontend tests** — 3,400 lines untested. No Vitest/Playwright. Rust shell also untested (`#[cfg(test)]` absent).
- **No auto-update** — no Tauri updater plugin. Versioning is manually triple-maintained: `config.APP_VERSION = "2.0.0"`, `tauri.conf.json = "2.0.0"`, `package.json = "0.0.0"` (**already drifted**).
- **No error reporting** — no Sentry, no crash dumps. User hits a bug → no telemetry.
- **Non-reproducible builds** — deps are range-pinned (`langchain >=0.3,<0.4`), no hash lockfile for Python. `package-lock.json` exists (good), but `requirements.txt` doesn't lock transitive deps.

#### Packaging Issues (Performance: 6/10)
- **One-file re-extraction cost** — PyInstaller one-file unpacks the 138MB bundle to a temp dir on every cold start (~3-5s). Slower than `--onedir` but simpler distribution.
- **Fixed 60s health probe** (`lib.rs:79`) — no graceful degradation if backend hangs. UI shows spinner for full minute before timeout.
- **First-run model download not masked** — 90MB `paraphrase-multilingual-MiniLM-L12-v2` downloads on first index with no splash/progress. User sees a frozen UI.
- **Native deps not bundled** — OCR (Tesseract/Poppler) and local LLM (llama.cpp) are advertised but silently no-op in the shipped binary. Should either bundle or hide the UI options.

---

## Prioritized Roadmap

### HIGH PRIORITY (Enterprise Blockers — Must Fix Before Calling It "Enterprise-Grade")

| Issue | Effort | Impact | File:Line |
|-------|--------|--------|-----------|
| **Add structured logging** | 2-3 hrs | Cannot diagnose field issues | All backend `print()` → `logging.info/error` |
| **Fix path traversal in upload** | 5 min | Critical security flaw | `main.py:92` — `os.path.basename(file.filename)` |
| **Add LICENSE file** | 10 min | Legally broken | Repo root — add MIT/Apache-2.0 |
| **Fix rapid-send race** | 15 min | Breaks chat UX | `ChatInterface.tsx:401` — disable examples while streaming |
| **Add AbortController to stream** | 30 min | Memory leak, wrong-session output | `ChatInterface.tsx:231` — abort on session change |
| **Fix BM25 cache bug** | 5 min | Keyword search returns stale results after delete | `indexing.py:249` — `self._bm25 = None` |
| **Separate prompt budgets** | 1-2 hrs | Long convos lose grounding | `generation.py:360-367` — history vs context budgets |
| **Add focus traps to modals** | 2-3 hrs | A11y blocker | `SettingsModal`, `HelpModal`, `FirstRunWizard`, `SourceModal` |
| **Add rehype-sanitize to markdown** | 15 min | XSS-adjacent | `ChatInterface.tsx:449` |
| **Rotate .env Groq key** | 5 min | Exposed secret | Delete from `.env`, add via Settings UI |

**Total: ~10-12 hours** for the true blockers.

---

### MEDIUM PRIORITY (Quality/UX — Needed for Portfolio Polish)

| Issue | Effort | Impact |
|-------|--------|--------|
| Add error boundary to React root | 30 min | Uncaught errors crash whole app |
| Add ARIA labels to icon buttons | 1 hr | A11y gap |
| Fix index-based message keys | 10 min | Flicker on reorder |
| Add auto-update (Tauri updater) | 2-3 hrs | Manual versioning broken |
| Add crash reporting (Sentry) | 1-2 hrs | No field telemetry |
| Decompose SettingsModal (706 lines) | 3-4 hrs | Unmaintainable |
| Add Vitest tests for SSE + key-entry flow | 4-6 hrs | Zero frontend coverage |
| Fix prompt-budget documentation | 30 min | Stale constants in IMPLEMENTATION_PLAN.md |
| Bundle Tesseract/Poppler or hide OCR UI | 4-6 hrs | Advertised feature silently no-ops |
| Add prefers-reduced-motion | 1 hr | A11y gap |
| Replace native alert/confirm with modal | 1 hr | Breaks visual language |
| Remove "4th Semester Project" footer | 2 min | Breaks enterprise illusion |

**Total: ~20-30 hours** for polish.

---

### LOW PRIORITY (Nice-to-Have / Long-Term)

| Issue | Effort | Impact |
|-------|--------|--------|
| Semantic chunking (sentence boundaries) | 1-2 days | Better retrieval |
| Contextual retrieval (chunk context injection) | 2-3 days | SOTA RAG |
| Query routing (specialized prompts by question type) | 1-2 days | Better answers |
| Metadata filtering UI | 2-3 days | Power-user feature |
| Incremental FAISS updates (no O(n) rebuild) | 2-3 days | Scalability |
| Deduplication on upload | 1 day | UX polish |
| Light theme | 2-3 days | A11y + aesthetics |
| i18n (internationalization) | 1 week | Global reach |
| Reproducible builds (lock transitive deps) | 1 day | Supply-chain security |
| Move PROVIDERS to separate file | 2 hrs | `config.py` decomposition |
| Add FAISS write lock | 1 hr | Concurrency safety |
| OS keyring integration | 2-3 days | Keystore hardening |

**Total: 2-4 weeks** for the full wishlist.

---

## Summary: What to Fix for the Next Session

If you have **one afternoon (4-6 hours)** before a demo/presentation:
1. Add LICENSE (10 min)
2. Fix path traversal (5 min)
3. Rotate .env key (5 min)
4. Fix rapid-send race (15 min)
5. Add AbortController (30 min)
6. Fix BM25 cache bug (5 min)
7. Add structured logging to main.py + generation.py (2 hrs)
8. Remove "4th Semester Project" footer (2 min)
9. Replace alert/confirm with modals (1 hr)
10. Add rehype-sanitize (15 min)

**= 5 hours, fixes all Critical + High-severity issues.**

If you have **a weekend (16 hours)**:
- Do the above +
- Separate prompt budgets (2 hrs)
- Add focus traps (3 hrs)
- Add error boundary (30 min)
- Add ARIA labels (1 hr)
- Decompose SettingsModal (4 hrs)
- Add 5-10 Vitest tests (3 hrs)
- Add auto-update (2 hrs)

**= Gets you to a legitimate 7.5-8/10 "enterprise-ready" bar.**

---

## Conclusion

This is a **strong, design-aware student project** with several genuinely production-minded touches (streaming correctness, provider fallback, encrypted keys, behavioral tests, honest UX). The RAG core is correctly implemented and well-tested. The architecture is sound.

**It is held back from "enterprise-grade" by operational maturity** (no logging, no tests on 40% of the codebase, no LICENSE, no observability) and **systemic accessibility failures** (no focus management, no ARIA, no reduced-motion).

The **highest-leverage fixes** are:
1. Add structured logging (~2 hrs) — solves the "cannot debug" blocker
2. Fix the 5 security/correctness bugs (1 hr total) — path traversal, rapid-send race, AbortController, BM25 cache, XSS-adjacent
3. Add LICENSE (10 min) — solves the legal blocker
4. Add focus traps + ARIA (3-4 hrs) — solves the a11y blocker

**Those four items (6-7 hours total) take this from a 6.5/10 to an 8/10.**

The rest is polish and long-term investment (semantic chunking, query routing, i18n, light theme, full test coverage). Totally achievable over the next 2-4 weeks if you chip away at it.

**You should be proud of what you've built.** Most student projects don't have working tests, let alone a mature provider-fallback strategy or encrypted key storage. This is legitimately portfolio-grade work — it just needs the operational layer to match the technical core.

---

**Audit completed 2026-06-27 by Claude (Anthropic).**  
**Next steps:** See `SESSION_HANDOFF.md` for the continuation prompt.