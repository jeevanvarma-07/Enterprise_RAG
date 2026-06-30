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

## Current state (updated 2026-07-01)

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
1. **⚠️ USER ACTION — rotate the Groq key.** `backend/.env` contains a REAL key
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
