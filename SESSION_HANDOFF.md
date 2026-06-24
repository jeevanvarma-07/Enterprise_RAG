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

## Current state (updated 2026-06-24)

Last commit: `dc2c263` — multilingual embeddings + PDF table parsing + live model
picker + Cerebras model-ID fix. Pushed to `origin/main`. Working tree clean.
All 101 backend tests pass; frontend `tsc -b` clean.

**What we're doing:** wiring the multi-provider LLM picker for the college demo —
pick a model in the top bar, paste a free per-provider API key in Settings, working
live (no refresh). Author collecting free API keys.

## Next steps (in priority order)
1. Test Cerebras live: reload the app, pick **Cerebras → GPT-OSS 120B**, confirm it
   answers without falling back to Groq. (Cerebras free tier = `gpt-oss-120b` +
   `zai-glm-4.7`; both reasoning models.)
2. As more free keys are obtained (have Gemini + Cerebras), report the exact model
   IDs and check/add them to `backend/config.py` `PROVIDERS`.
3. **Open decision:** make Cerebras GPT-OSS the *default* model (roomier free tier)
   instead of Groq `llama-3.1-8b-instant`? — undecided.
4. Bigger plan items still open: offline LLM (llama.cpp + GGUF download, Phase 1);
   Phase 3 laptop profiling; Phase 5 branding/licensing.

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
