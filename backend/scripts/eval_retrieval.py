"""
Retrieval evaluation harness.

Measures the *retrieval* layer (dense + BM25 + RRF + optional reranking) so
changes to the tuning knobs are measured, not guessed. It deliberately skips
the LLM (no multi-query rewrite, no answer generation) — that keeps the harness
offline, deterministic, and free, and isolates retrieval quality from model
variance.

Two ways to run:

    # 1. Zero-setup synthetic corpus (great for a quick sanity check / demo)
    python -m scripts.eval_retrieval

    # 2. Against your own data + a Q/A file, comparing config presets
    python -m scripts.eval_retrieval --dataset eval/my_questions.json --use-store

Dataset format (JSON list); a hit = any expected substring appears (case-
insensitively) in a retrieved chunk:

    [
      {"query": "what is the refund window?", "expects": ["30 days"]},
      {"query": "role of employee 7741?",     "expects": ["Data Scientist"]}
    ]

Metrics per config: Recall@final_k (share of questions with at least one hit)
and MRR (mean reciprocal rank of the first hit). Higher is better for both.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from typing import Any, Dict, List, Optional

import config
from services.generation import reciprocal_rank_fusion
from services.indexing import VectorStoreManager


# ─────────────────────────────────────────────────────────────────────
# Synthetic corpus — a handful of short, unambiguous facts. A few queries
# are paraphrases (dense search shines) and a few hinge on exact tokens
# like an ID or "Q3" (BM25 shines), so hybrid should beat dense-only.
# ─────────────────────────────────────────────────────────────────────
SYNTHETIC_DOCS: List[str] = [
    "The Eiffel Tower is located in Paris, France and was completed in 1889.",
    "Photosynthesis is the process by which green plants convert sunlight into "
    "chemical energy stored as glucose.",
    "Employee ID 7741 is assigned to Priya Nair, who works as a Data Scientist "
    "in the Analytics team.",
    "The quarterly revenue for Q3 reached 4.2 million dollars, up 12 percent "
    "year over year.",
    "Mount Everest is the highest mountain above sea level, standing at 8849 "
    "meters in the Himalayas.",
    "The return policy allows refunds within 30 days of purchase, provided the "
    "item is unused and in its original packaging.",
]

SYNTHETIC_DATASET: List[Dict[str, Any]] = [
    {"query": "Where is the Eiffel Tower?", "expects": ["Paris"]},
    {"query": "How do plants make energy from light?", "expects": ["Photosynthesis"]},
    {"query": "What is the role of employee 7741?", "expects": ["Data Scientist"]},
    {"query": "How tall is the tallest mountain on Earth?", "expects": ["8849"]},
    {"query": "What is the refund window?", "expects": ["30 days"]},
    {"query": "What was the Q3 revenue figure?", "expects": ["4.2 million"]},
]


# Config presets compared side by side. Each overrides retrieval_params().
def _presets(base: Dict[str, Any]) -> "Dict[str, Dict[str, Any]]":
    """Build the comparison presets from a base param set."""
    dense = dict(base, bm25_k=0)
    hybrid = dict(base)
    return {
        "dense-only": {"params": dense, "rerank": False},
        "hybrid": {"params": hybrid, "rerank": False},
        "hybrid+rerank": {"params": hybrid, "rerank": True},
    }


# ─────────────────────────────────────────────────────────────────────
# Core single-query retrieval (no LLM): dense MMR + BM25 → RRF → rerank.
# ─────────────────────────────────────────────────────────────────────
def retrieve(
    vm: VectorStoreManager,
    query: str,
    params: Dict[str, Any],
    use_rerank: bool = False,
) -> List[Any]:
    """Return the ranked Documents for one query under the given params."""
    results: List[List[Any]] = []

    retriever = vm.as_retriever(
        search_kwargs={
            "k": params["top_k"],
            "fetch_k": params["fetch_k"],
            "lambda_mult": params["mmr_lambda"],
        }
    )
    if retriever is not None:
        try:
            results.append(retriever.invoke(query))
        except Exception:
            pass

    if params["bm25_k"] > 0:
        bm25 = vm.bm25_retriever(k=params["bm25_k"])
        if bm25 is not None:
            try:
                results.append(bm25.invoke(query))
            except Exception:
                pass

    fused = reciprocal_rank_fusion(results)

    if use_rerank:
        try:
            from services.reranker import rerank
            return rerank(query, fused[: params["rerank_candidates"]], top_n=params["final_k"])
        except Exception:
            pass
    return fused[: params["final_k"]]


# ─────────────────────────────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────────────────────────────
def _first_hit_rank(docs: List[Any], expects: List[str]) -> int:
    """1-based rank of the first chunk containing any expected substring, else 0."""
    wants = [e.lower() for e in expects]
    for i, d in enumerate(docs):
        text = (getattr(d, "page_content", "") or "").lower()
        if any(w in text for w in wants):
            return i + 1
    return 0


def evaluate(
    vm: VectorStoreManager,
    dataset: List[Dict[str, Any]],
    params: Dict[str, Any],
    use_rerank: bool = False,
) -> Dict[str, Any]:
    """Run every question once and aggregate Recall@k and MRR."""
    hits = 0
    rr_sum = 0.0
    per_query: List[Dict[str, Any]] = []
    for item in dataset:
        docs = retrieve(vm, item["query"], params, use_rerank)
        rank = _first_hit_rank(docs, item.get("expects", []))
        hit = rank > 0
        hits += 1 if hit else 0
        rr_sum += (1.0 / rank) if rank else 0.0
        per_query.append({"query": item["query"], "rank": rank, "hit": hit})

    n = max(1, len(dataset))
    return {
        "recall": hits / n,
        "mrr": rr_sum / n,
        "n": len(dataset),
        "per_query": per_query,
    }


def run_suite(
    vm: VectorStoreManager,
    dataset: List[Dict[str, Any]],
    base_params: Optional[Dict[str, Any]] = None,
    include_rerank: bool = False,
) -> "Dict[str, Dict[str, Any]]":
    """Evaluate every preset and return {preset_name: metrics}."""
    base = base_params or config.retrieval_params()
    out: Dict[str, Dict[str, Any]] = {}
    for name, spec in _presets(base).items():
        if spec["rerank"] and not include_rerank:
            continue
        out[name] = evaluate(vm, dataset, spec["params"], use_rerank=spec["rerank"])
    return out


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────
def _build_synthetic_store() -> VectorStoreManager:
    """Index the synthetic corpus into a throwaway temp store."""
    tmp = tempfile.mkdtemp(prefix="rag_eval_")
    vm = VectorStoreManager(index_path=tmp)
    vm.add_documents(SYNTHETIC_DOCS, source_filename="synthetic.txt")
    return vm


def _print_report(results: "Dict[str, Dict[str, Any]]") -> None:
    print()
    print(f"{'config':<16}{'Recall@k':>10}{'MRR':>8}{'N':>5}")
    print("-" * 39)
    for name, m in results.items():
        print(f"{name:<16}{m['recall']:>10.2f}{m['mrr']:>8.2f}{m['n']:>5}")
    print()


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate RAG retrieval quality.")
    ap.add_argument("--dataset", help="JSON file of {query, expects[]} items.")
    ap.add_argument("--use-store", action="store_true",
                    help="Evaluate against the real on-disk vector store instead of the synthetic corpus.")
    ap.add_argument("--rerank", action="store_true",
                    help="Also evaluate the rerank preset (loads flashrank; may download the model).")
    args = ap.parse_args(argv)

    # Dataset
    if args.dataset:
        with open(args.dataset, "r", encoding="utf-8") as f:
            dataset = json.load(f)
    else:
        dataset = SYNTHETIC_DATASET

    # Store
    if args.use_store:
        vm = VectorStoreManager()  # real configured store
        if not vm.is_loaded():
            print("No vector store found — upload/index documents first, or omit --use-store.")
            return 1
        if not args.dataset:
            print("Warning: --use-store with the synthetic dataset rarely matches your docs; "
                  "pass --dataset for meaningful numbers.")
    else:
        vm = _build_synthetic_store()

    results = run_suite(vm, dataset, include_rerank=args.rerank)
    _print_report(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
