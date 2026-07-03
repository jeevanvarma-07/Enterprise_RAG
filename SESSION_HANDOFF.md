# Session Handoff — read this first

**Purpose:** This file carries cross-session state *in the repo* so work continues
smoothly on any machine (desktop ⇄ laptop) and any Claude Code session, without
re-deriving context. **Claude memory does NOT sync between machines — this file
does (via git).** Update + commit it at the END of every working session.

> Start-of-session checklist (cheap, ~no wasted tokens):
> 1. `git pull`
> 2. Tell Claude: **"Read CLAUDE.md, IMPLEMENTATION_PLAN.md, and SESSION_HANDOFF.md, then continue."**
> 3. If first time on this machine: `cd backend && python -m venv venv && pip install -r requirements.txt`; `cd frontend && npm install`; re-enter API keys in Settings → LLM Providers (keys do NOT travel).

---

## Current state (updated 2026-07-03 — later session)

**RAGAS Evaluation Dashboard — shipped this session.** The headline remaining feature from
the project prompt is done: the four canonical RAG-quality metrics, hand-rolled and
Lite-safe, with a full Evaluation tab. Backend: **132 tests pass (1 skipped)** (was 116).
Frontend: `tsc -b` clean + `vite build` succeeds.

Done this session (2026-07-03, later) — planned then built end-to-end:
1. **Eval engine** — NEW `services/evaluation.py`. Hand-rolled metrics reusing the configured
   LLM-judge (`providers.build_chat_model`, temp 0) + local embeddings — **not** the pip
   `ragas` package (heavy, wants newer Python; this repo runs 3.9 on Lite). Four metrics,
   each `{score: float|None, detail}`, never raises (judge/parse failure → `null`):
   **faithfulness** (claims extracted from answer, verdicted vs contexts),
   **answer_relevancy** (N=3 reverse-questions embedded, mean cosine to original;
   noncommittal → 0), **context_precision** (RAGAS rank-weighted precision@k),
   **context_recall** (ground-truth claims attributable to contexts; `null` w/o labels).
   `evaluate(...)` orchestrates, filling answer/contexts via the pipeline when absent.
2. **Storage** — `storage.py`: `eval_runs` table + `record_eval_run` / `recent_evals` /
   `eval_summary` (COUNT + null-safe AVG of the four), mirroring the `request_metrics` shape.
3. **API** — `main.py`: `POST /api/eval/run` (live single question, threadpooled),
   `POST /api/eval/dataset` (sequential, capped at 25 items for free-tier TPM),
   `GET /api/eval/summary`, `GET /api/eval/recent?limit=`. `eval_provider`/`eval_model`
   optional settings.
4. **Frontend** — NEW `components/EvaluationDashboard.tsx` (Evaluation tab, `BarChart3`
   nav item): header/aggregate cards, hand-rolled 0–1 bar gauges (zero chart deps), run
   panel (question + optional ground-truth), dataset runner, recent-evals table. Reuses the
   existing `/api/metrics/summary` for the tokens/latency strip.
5. **Fixtures + tests** — `eval/ragas_example.json` (6 labelled Q+ground_truth, zero-setup
   demo); `tests/test_evaluation.py` (16 tests, stubbed judge + toy embedder, fully offline).

On-demand only — zero passive per-chat overhead. Committed per concern (eval engine → storage
→ API → frontend → tests → docs) on top of the prior session's work.

**Next big item = polish / release (Phase 5):** packaged-app boot smoke-test in CI, the
remaining MEDIUM audit items (focus traps, error boundary, ARIA), and the deferred offline
LLM (llama.cpp + GGUF). No headline feature outstanding.

---

## Prior state (updated 2026-07-03 — earlier session)

**Retrieval Inspector + per-request telemetry + reliability + duplicate detection —
shipped.** Backend: **116 tests pass (1 skipped)** (was 101). Frontend `tsc -b` clean +
`vite build` succeeds. All committed on top of `2bcc834`.

1. **Retrieval Inspector (backend)** — `services/inspection.py` `RetrievalTrace`: opt-in,
   zero-overhead-when-off, best-effort trace of every pipeline stage; streams an `inspection`
   SSE event when on.
2. **Telemetry** — streaming returns `(answer, usage)` and emits `done{metrics}`;
   `storage.request_metrics` table + `record_request_metric` / `recent_metrics` /
   `metrics_summary`.
3. **Reliability** — `generation._retry_transient`: exp-backoff+jitter retry of the SAME
   provider for transient errors before falling back; non-transient errors re-raise.
4. **Duplicate detection** — `document_processing.content_hash` + `indexing.find_duplicate`;
   upload + URL scrape skip re-indexing identical content.
5. **Frontend** — `RetrievalInspector.tsx` + `MetricsBar`; `SettingsModal` default-off toggle.
6. **Tests** — `tests/test_inspection_and_metrics.py` (13). Backend landed as one broad
   commit (`7864051`); frontend its own commit.

---

## Prior state (updated 2026-07-01)

**Most of the audit's HIGH-priority "critical path" is now implemented** (see
`TECHNICAL_AUDIT_2026-06-27.md` for the full 6.5/10 audit that drove this work).
Backend: 101 tests pass (1 skipped). Frontend: `tsc -b` clean + `vite build` succeeds.

Done this session (2026-07-01):
1. **LICENSE** — added MIT (`LICENSE`, © Jeevan Varma R). Repo no longer all-rights-reserved.
2. **Path traversal fixed** — `main.py` `_process_one` now `os.path.basename()`-sanitizes
   the uploaded filename (rejects empty/`.`/`..`) and uses the safe name for save +
   indexing + status, so a crafted `../../x` name can't escape `uploads/`.
3. **BM25 cache on delete** — was ALREADY correct in current code (`indexing.py`
   `delete_by_source` resets `self._bm25 = None`); audit line had drifted. No change needed.
4. **Rapid-send race fixed** — `ChatInterface.tsx`: `sendingRef` lock guards re-entrant
   `handleSend`; example-query buttons are `disabled={loading}`.
5. **AbortController** — `ChatInterface.tsx`: stream fetch carries an `AbortController`
   (`abortRef`); the session-change effect cleanup aborts it; `AbortError` is swallowed so
   a switched-away bubble is left untouched. Refs cleared in `finally`.
6. **rehype-sanitize** — installed `rehype-sanitize@^6`; AI markdown now renders with
   `rehypePlugins={[rehypeSanitize]}` (strips `javascript:` hrefs etc.).
7. **"4th Semester Project" footer removed** — `LandingPage.tsx` footer reworded to a
   neutral "Local-first document intelligence · FastAPI + React + FAISS".
8. **Structured logging** — new `services/logging_config.py` (`setup_logging()`: console +
   `RotatingFileHandler` → `DATA_DIR/logs/app.log`, 2 MB×5, `RAG_LOG_LEVEL` env). Wired in
   `main.py` at startup. Replaced ALL `print()` in `services/` (document_processing,
   indexing, generation, embeddings, reranker, table_extraction) with `logging`. New
   `config.LOGS_DIR` (created by `ensure_dirs`). Updated `test_embeddings.py`
   mismatch-warning test to assert via `caplog` instead of `capsys`.
9. **alert/confirm → modals** — new reusable `components/ConfirmDialog.tsx` (portal,
   Escape/backdrop close, `role="dialog"`, focuses confirm btn). `VectorStoreTab.tsx` now
   uses it for batch-delete + clear-all, and an inline dismissible error banner replaces
   the `alert()` failures.

Default LLM is Cerebras GPT-OSS 120B.

**Committed 2026-07-01** (next session): the work above + the demo-build cleanup landed as
8 focused, per-concern commits on top of `1b3b152` — gitignore DEMO_TRANSFER → security
(filename + markdown sanitize) → structured logging → chat-race/abort → a11y ConfirmDialog →
MIT LICENSE → footer reword → this docs/handoff update. Verified before committing: backend
`pytest` 101 passed / 1 skipped, frontend `tsc -b` clean. Not pushed yet.

## Next steps (in priority order)
1. ~~**RAGAS Evaluation Dashboard**~~ — DONE 2026-07-03 (later session). Four hand-rolled
   Lite-safe metrics + `/api/eval/*` + Evaluation tab; see Current state. No headline feature
   outstanding.
2. **⚠️ USER ACTION — rotate the Groq key.** `backend/.env` contains a REAL key
   (`GROQ_API_KEY="gsk_…"`), not a placeholder. Rotate it at console.groq.com, delete the
   line from `.env`, and re-add the new key via Settings → LLM Providers (encrypted store).
   Left in place for now so dev Groq access isn't broken before rotation. (User said they'd
   rotate it themselves — still pending as of 2026-07-01.)
2. ~~Commit the session's work~~ — DONE 2026-07-01 (split per concern; see Current state).
   Optional follow-up: `git push` when ready.
3. (Optional) MEDIUM-priority audit items not yet done: separate prompt budgets
   (`generation.py`), focus traps on the OTHER modals (Settings/Help/FirstRun/Source),
   React error boundary, ARIA labels on icon buttons, `prefers-reduced-motion`,
   index-based message keys → `key={msg.id || idx}`, frontend Vitest tests.
4. Bigger plan items still open: offline LLM (llama.cpp + GGUF); laptop profiling.

## Cross-machine gotchas
- **API keys** (`keys.enc`/`secret.key`/`.env`) are gitignored → re-enter per machine.
- **vector_store/ + uploads/** are gitignored → re-upload & re-index docs per machine.
- **graphify-out/** is NOT committed → regenerate with `graphify update .` if you
  want the knowledge graph on a machine (optional; saves Claude tokens on code Qs).
- Backend Python is **3.9** here → Docling/torch table engine auto-skips (pdfplumber
  is the default). A machine with 3.10+ can opt into Docling.

## Free providers / model IDs (free tier)
Gemini `gemini-2.0-flash` · Cerebras `gpt-oss-120b`/`zai-glm-4.7` ·
Groq `llama-3.1-8b-instant`/`llama-3.3-70b-versatile` (6k TPM cap) ·
NVIDIA `meta/llama-3.3-70b-instruct` · Mistral `mistral-small-latest` ·
OpenRouter `meta-llama/llama-3.3-70b-instruct:free`.
Note: provider free catalogues change — if a model 404s, query
`GET <base_url>/v1/models` with the key to get the live list, then update PROVIDERS.
