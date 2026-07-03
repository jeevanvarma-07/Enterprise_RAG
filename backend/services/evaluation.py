"""
RAG answer-quality evaluation — a hand-rolled, Lite-safe RAGAS.

Why hand-rolled (not the `ragas` pip package)
----------------------------------------------
The canonical `ragas` library is heavy (pulls the `datasets` / large pydantic
stacks, wants a newer Python) and would break the 8 GB / Python-3.9 Lite path
this app targets. So the four RAGAS metrics are implemented here directly,
reusing what the app already loads:

  - the configured free LLM as a *judge* (services.providers.build_chat_model)
  - the local embeddings model (services.embeddings.get_embeddings)

That keeps evaluation free, offline-capable, and dependency-free. It mirrors the
existing hand-rolled retrieval harness (scripts/eval_retrieval.py).

The four metrics
----------------
  faithfulness       answer + contexts        is every claim grounded in context?
  answer_relevancy   question + answer         does the answer address the question?
  context_precision  question + contexts       are the retrieved chunks on-topic,
                                                and ranked well?
  context_recall     ground_truth + contexts   does retrieval cover the reference
                                                answer?  (needs a labelled answer;
                                                null in label-free "live" mode)

Design rules (match services/inspection.py):
  - Every public function is best-effort and NEVER raises: on any judge/parse
    failure a metric returns score=None, so evaluation degrades gracefully and
    a bad provider can't crash a request.
  - Evaluation is ON-DEMAND only (no passive per-chat overhead) → Lite-safe.
"""

from __future__ import annotations

import json
import math
import re
import time
from typing import Any, List, Optional, Tuple

from langchain_core.messages import HumanMessage

import config
from services import providers

# How many "reverse questions" answer-relevancy generates from the answer.
_RELEVANCY_N = 3
# Noncommittal answers score 0 for relevancy regardless of similarity.
_NONCOMMITTAL = re.compile(
    r"\b(i (don'?t|do not) know|no (relevant )?(information|answer|data)|"
    r"cannot (be )?(answer|found|determine)|not (found|available|mentioned))\b",
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────────────
# Judge plumbing
# ─────────────────────────────────────────────────────────────────────
def judge_target() -> Tuple[Optional[str], str]:
    """
    (provider, model) to use as the LLM judge.

    Prefers explicit `eval_provider` / `eval_model` settings; otherwise reuses
    the same provider/model the app chats with, so evaluation needs no extra
    keys. Falls back to the app defaults.
    """
    s = config.get_settings()
    provider = s.get("eval_provider") or s.get("active_provider") or config.DEFAULT_PROVIDER
    model = s.get("eval_model") or s.get("active_model") or config.DEFAULT_MODEL
    return (provider or None), model


def _judge(
    prompt: str,
    provider: Optional[str],
    model: str,
    max_tokens: int = 1024,
) -> Tuple[Optional[str], Optional[dict]]:
    """
    One guarded LLM-judge call at temperature 0 (deterministic-as-possible).

    Returns (text, usage) — (None, None) on any failure, so callers can treat a
    dead provider as "unknown" rather than an exception.
    """
    try:
        llm = providers.build_chat_model(
            provider, model, temperature=0.0, max_tokens=max_tokens
        )
        msg = llm.invoke([HumanMessage(content=prompt)])
        text = getattr(msg, "content", "") or ""
        usage = providers.extract_usage(msg)
        return text, usage
    except Exception:
        return None, None


def _parse_json(text: Optional[str]) -> Any:
    """
    Pull a JSON value out of a judge reply, tolerating ```json fences and
    surrounding prose. Returns the parsed value or None.
    """
    if not text:
        return None
    # Strip code fences.
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    # Fallback: grab the first {...} or [...] span and try that.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if 0 <= start < end:
            try:
                return json.loads(cleaned[start : end + 1])
            except Exception:
                continue
    return None


def _yes(val: Any) -> bool:
    """Truthy verdict from a judge (handles bool, 1/0, 'yes'/'true'/'supported')."""
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val >= 1
    s = str(val).strip().lower()
    return s in ("1", "yes", "y", "true", "supported", "attributed", "relevant", "present")


def _cosine(a: List[float], b: List[float]) -> float:
    """Cosine similarity of two vectors (0.0 on degenerate input)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _fmt_contexts(contexts: List[str]) -> str:
    """Number the retrieved chunks for the judge prompts."""
    return "\n\n".join(f"[{i + 1}] {c}" for i, c in enumerate(contexts) if c)


# ─────────────────────────────────────────────────────────────────────
# Metric 1 — Faithfulness  (answer grounded in the retrieved context)
# ─────────────────────────────────────────────────────────────────────
def faithfulness(
    answer: str, contexts: List[str], provider: Optional[str] = None, model: str = ""
) -> dict:
    """
    Fraction of the answer's atomic claims that are supported by the context.

    Two judge calls: (1) break the answer into standalone claims, (2) verdict
    each claim against the context. score = supported / total (1.0 if no claims,
    None if the judge is unavailable).
    """
    provider = provider if provider is not None else judge_target()[0]
    model = model or judge_target()[1]
    if not (answer or "").strip() or not contexts:
        return {"score": None, "detail": {"reason": "no answer or no context"}}

    claim_prompt = (
        "Break the following ANSWER into a JSON array of short, self-contained "
        "factual statements (claims). Return ONLY the JSON array.\n\n"
        f"ANSWER:\n{answer}"
    )
    text, u1 = _judge(claim_prompt, provider, model)
    claims = _parse_json(text)
    if not isinstance(claims, list) or not claims:
        # Fall back to treating the whole answer as one claim.
        claims = [answer.strip()]
        u1 = u1 or None
    claims = [str(c) for c in claims][:20]

    verdict_prompt = (
        "For each CLAIM, decide if it can be inferred from the CONTEXT. "
        "Reply ONLY with a JSON array of booleans, one per claim, in order.\n\n"
        f"CONTEXT:\n{_fmt_contexts(contexts)}\n\n"
        f"CLAIMS:\n{json.dumps(claims, ensure_ascii=False)}"
    )
    text2, u2 = _judge(verdict_prompt, provider, model)
    verdicts = _parse_json(text2)
    if not isinstance(verdicts, list) or not verdicts:
        return {"score": None, "detail": {"reason": "judge unavailable", "claims": claims}}

    supported = sum(1 for v in verdicts[: len(claims)] if _yes(v))
    total = len(claims)
    return {
        "score": supported / total if total else 1.0,
        "detail": {"supported": supported, "total": total, "claims": claims},
        "usage": _sum_usage(u1, u2),
    }


# ─────────────────────────────────────────────────────────────────────
# Metric 2 — Answer relevancy  (answer actually addresses the question)
# ─────────────────────────────────────────────────────────────────────
def answer_relevancy(
    question: str, answer: str, provider: Optional[str] = None, model: str = ""
) -> dict:
    """
    Generate N questions the answer would answer, then measure their mean
    embedding-cosine similarity to the ORIGINAL question. A focused, on-topic
    answer yields reverse-questions close to the real one. Noncommittal answers
    ("I don't know") score 0.
    """
    provider = provider if provider is not None else judge_target()[0]
    model = model or judge_target()[1]
    if not (answer or "").strip():
        return {"score": None, "detail": {"reason": "empty answer"}}
    if _NONCOMMITTAL.search(answer):
        return {"score": 0.0, "detail": {"reason": "noncommittal answer"}}

    gen_prompt = (
        f"Given this ANSWER, generate {_RELEVANCY_N} different questions that the "
        "answer would be a direct response to. Return ONLY a JSON array of strings.\n\n"
        f"ANSWER:\n{answer}"
    )
    text, usage = _judge(gen_prompt, provider, model)
    gen_qs = _parse_json(text)
    if not isinstance(gen_qs, list) or not gen_qs:
        return {"score": None, "detail": {"reason": "judge unavailable"}}
    gen_qs = [str(q) for q in gen_qs][:_RELEVANCY_N]

    try:
        emb = _get_embeddings()
        q_vec = emb.embed_query(question)
        sims = [_cosine(q_vec, emb.embed_query(g)) for g in gen_qs]
    except Exception:
        return {"score": None, "detail": {"reason": "embeddings unavailable",
                                          "generated": gen_qs}}
    # Clamp to [0,1] — cosine can dip slightly negative for unrelated text.
    score = max(0.0, min(1.0, sum(sims) / len(sims))) if sims else 0.0
    return {
        "score": score,
        "detail": {"generated": gen_qs, "similarities": [round(s, 3) for s in sims]},
        "usage": usage,
    }


# ─────────────────────────────────────────────────────────────────────
# Metric 3 — Context precision  (retrieved chunks are on-topic & ranked well)
# ─────────────────────────────────────────────────────────────────────
def context_precision(
    question: str,
    contexts: List[str],
    answer: str = "",
    provider: Optional[str] = None,
    model: str = "",
) -> dict:
    """
    Judge each retrieved chunk useful/not for answering the question, then
    compute RAGAS-style rank-weighted precision@k (a relevant chunk high in the
    list counts for more than one buried at the bottom).
    """
    provider = provider if provider is not None else judge_target()[0]
    model = model or judge_target()[1]
    contexts = [c for c in (contexts or []) if c]
    if not contexts:
        return {"score": None, "detail": {"reason": "no context"}}

    ref = f"\n\nREFERENCE ANSWER (for judging usefulness):\n{answer}" if answer else ""
    prompt = (
        "For each numbered CONTEXT chunk, decide if it is useful for answering "
        "the QUESTION. Reply ONLY with a JSON array of booleans, one per chunk, "
        "in order.\n\n"
        f"QUESTION: {question}{ref}\n\n"
        f"CONTEXT:\n{_fmt_contexts(contexts)}"
    )
    text, usage = _judge(prompt, provider, model)
    verdicts = _parse_json(text)
    if not isinstance(verdicts, list) or not verdicts:
        return {"score": None, "detail": {"reason": "judge unavailable"}}

    rel = [1 if _yes(v) else 0 for v in verdicts[: len(contexts)]]
    # RAGAS context precision: mean of precision@k at every rank that IS relevant.
    num_relevant = sum(rel)
    if num_relevant == 0:
        return {"score": 0.0, "detail": {"relevant": rel}}
    cum = 0
    weighted = 0.0
    for k, is_rel in enumerate(rel, start=1):
        if is_rel:
            cum += 1
            weighted += cum / k
    score = weighted / num_relevant
    return {
        "score": max(0.0, min(1.0, score)),
        "detail": {"relevant": rel, "num_relevant": num_relevant},
        "usage": usage,
    }


# ─────────────────────────────────────────────────────────────────────
# Metric 4 — Context recall  (retrieval covers the reference answer)
# ─────────────────────────────────────────────────────────────────────
def context_recall(
    ground_truth: str,
    contexts: List[str],
    provider: Optional[str] = None,
    model: str = "",
) -> dict:
    """
    Split the GROUND-TRUTH answer into claims, then measure the fraction that
    can be attributed to the retrieved context. Needs a labelled answer — returns
    None (skipped) when no ground_truth is supplied (label-free live mode).
    """
    provider = provider if provider is not None else judge_target()[0]
    model = model or judge_target()[1]
    if not (ground_truth or "").strip():
        return {"score": None, "detail": {"reason": "no ground truth"}}
    contexts = [c for c in (contexts or []) if c]
    if not contexts:
        return {"score": 0.0, "detail": {"reason": "no context retrieved"}}

    prompt = (
        "Break the GROUND-TRUTH answer into short factual claims, and for each "
        "decide if it can be attributed to (found in) the CONTEXT. Reply ONLY "
        "with a JSON array of booleans, one per claim, in order.\n\n"
        f"CONTEXT:\n{_fmt_contexts(contexts)}\n\n"
        f"GROUND-TRUTH:\n{ground_truth}"
    )
    text, usage = _judge(prompt, provider, model)
    verdicts = _parse_json(text)
    if not isinstance(verdicts, list) or not verdicts:
        return {"score": None, "detail": {"reason": "judge unavailable"}}

    attributed = sum(1 for v in verdicts if _yes(v))
    total = len(verdicts)
    return {
        "score": attributed / total if total else None,
        "detail": {"attributed": attributed, "total": total},
        "usage": usage,
    }


# ─────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────
def evaluate(
    question: str,
    answer: Optional[str] = None,
    contexts: Optional[List[str]] = None,
    ground_truth: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    """
    Run the four metrics for one (question[, answer, contexts, ground_truth]).

    If `answer`/`contexts` are omitted, they're produced by running the real RAG
    pipeline for `question` (so the dashboard can evaluate a live answer from just
    a question). Returns a flat result ready for storage + the UI:

      {question, answer, contexts, ground_truth,
       faithfulness, answer_relevancy, context_precision, context_recall,
       details:{...}, eval_provider, eval_model, eval_tokens, eval_latency_ms}

    Never raises; unavailable metrics come back as None.
    """
    t0 = time.perf_counter()
    jp, jm = judge_target()
    provider = provider if provider is not None else jp
    model = model or jm

    # Fill in answer + contexts from the live pipeline when not supplied.
    if answer is None or contexts is None:
        answer, contexts = _run_pipeline(question)

    answer = answer or ""
    contexts = contexts or []

    m_faith = faithfulness(answer, contexts, provider, model)
    m_rel = answer_relevancy(question, answer, provider, model)
    m_prec = context_precision(question, contexts, answer, provider, model)
    m_recall = context_recall(ground_truth or "", contexts, provider, model)

    tokens = 0
    for m in (m_faith, m_rel, m_prec, m_recall):
        u = m.get("usage")
        if isinstance(u, dict):
            tokens += int(u.get("total") or 0)

    return {
        "question": question,
        "answer": answer,
        "contexts": contexts,
        "ground_truth": ground_truth,
        "faithfulness": m_faith["score"],
        "answer_relevancy": m_rel["score"],
        "context_precision": m_prec["score"],
        "context_recall": m_recall["score"],
        "details": {
            "faithfulness": m_faith.get("detail"),
            "answer_relevancy": m_rel.get("detail"),
            "context_precision": m_prec.get("detail"),
            "context_recall": m_recall.get("detail"),
        },
        "eval_provider": provider,
        "eval_model": model,
        "eval_tokens": tokens,
        "eval_latency_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


# ─────────────────────────────────────────────────────────────────────
# Lazy helpers (kept out of module import so the Lite path stays cheap and
# tests can monkeypatch them without a real model/index)
# ─────────────────────────────────────────────────────────────────────
def _get_embeddings():
    """The active local embeddings model (same one used for indexing)."""
    from services.embeddings import get_embeddings

    return get_embeddings()


def _run_pipeline(question: str) -> Tuple[str, List[str]]:
    """
    Run the real RAG pipeline for `question` and return (answer, contexts) where
    contexts are the final retrieved chunk texts. Best-effort — ("", []) on error.
    """
    try:
        from services.generation import RAGPipeline
        from services.indexing import VectorStoreManager

        pipeline = RAGPipeline(VectorStoreManager())
        answer, sources, _notice = pipeline.generate_response(question)
        contexts = [s.get("text", "") for s in (sources or []) if s.get("text")]
        return answer, contexts
    except Exception:
        return "", []


def _sum_usage(*usages: Optional[dict]) -> Optional[dict]:
    """Add up token totals across several judge calls (None-safe)."""
    total = 0
    seen = False
    for u in usages:
        if isinstance(u, dict) and u.get("total"):
            total += int(u["total"])
            seen = True
    return {"total": total} if seen else None
