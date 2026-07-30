"""Retrieval evaluation against the golden set.

Runs IN-PROCESS against the RetrievalService (services must be up and the
corpus ingested). Typical invocation:

    docker compose exec api python eval/run_eval.py
    docker compose exec api python eval/run_eval.py --out /tmp/results.json

Metrics:
  - recall@fetch : answerable queries where >=1 relevant chunk is in the
                   pooled pre-rerank candidates (retrieval ceiling)
  - hit@k        : answerable queries with a relevant chunk in the final top-k
  - mrr@k        : mean reciprocal rank of the first relevant final chunk
  - abstention   : unanswerable queries where retrieval correctly returned
                   nothing (score floor working as intended)

A chunk is "relevant" when its source is in expected_sources AND (keywords
empty OR any keyword appears in its text, case-insensitive). Run this before
and after every knob change — no tuning without a delta.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import get_settings  # noqa: E402
from services.container import build_container  # noqa: E402


def is_relevant(text: str, source: str, entry: dict) -> bool:
    if source not in entry["expected_sources"]:
        return False
    keywords = entry.get("expected_keywords") or []
    if not keywords:
        return True
    lowered = text.lower()
    return any(k.lower() in lowered for k in keywords)


def evaluate(golden_path: str, k: int):
    settings = get_settings()
    retrieval = build_container(settings).retrieval

    with open(golden_path, encoding="utf-8") as f:
        entries = json.load(f)["entries"]

    rows = []
    for entry in entries:
        question = entry["question"]
        if entry["answerable"]:
            candidates = retrieval.fetch_candidates(question, filters=None)
            pre_hit = any(
                is_relevant(c.text, c.payload.get("source", ""), entry) for c in candidates
            )
            chunks = retrieval.retrieve(question, filters=None, k=k)
            first_rank = next(
                (rank for rank, c in enumerate(chunks, 1) if is_relevant(c.text, c.source, entry)),
                None,
            )
            rows.append({
                "question": question,
                "language": entry["language"],
                "kind": "answerable",
                "recall_at_fetch": pre_hit,
                "hit_at_k": first_rank is not None,
                "reciprocal_rank": (1.0 / first_rank) if first_rank else 0.0,
                "returned": len(chunks),
                "top_score": chunks[0].score if chunks else None,
            })
        else:
            chunks = retrieval.retrieve(question, filters=None, k=k)
            rows.append({
                "question": question,
                "language": entry["language"],
                "kind": "abstention",
                "abstained_correctly": len(chunks) == 0,
                "returned": len(chunks),
                "top_score": chunks[0].score if chunks else None,
            })

    answerable = [r for r in rows if r["kind"] == "answerable"]
    abstention = [r for r in rows if r["kind"] == "abstention"]

    def rate(items, key):
        return round(sum(1 for i in items if i[key]) / len(items), 3) if items else None

    summary = {
        "config": {
            "reranker": settings.reranker_model,
            "score_floor": settings.rerank_score_floor,
            "fetch_k": settings.retrieval_fetch_k,
            "top_n": k,
            "context_mode": settings.retrieval_context_mode,
        },
        "n_answerable": len(answerable),
        "n_abstention": len(abstention),
        "recall_at_fetch": rate(answerable, "recall_at_fetch"),
        "hit_at_k": rate(answerable, "hit_at_k"),
        "mrr_at_k": round(sum(r["reciprocal_rank"] for r in answerable) / len(answerable), 3) if answerable else None,
        "abstention_accuracy": rate(abstention, "abstained_correctly"),
    }
    for lang in sorted({r["language"] for r in answerable}):
        subset = [r for r in answerable if r["language"] == lang]
        summary[f"hit_at_k[{lang}]"] = rate(subset, "hit_at_k")

    return summary, rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval against the golden set.")
    parser.add_argument("--golden", default=os.path.join(os.path.dirname(__file__), "golden_set.json"))
    parser.add_argument("--k", type=int, default=get_settings().rerank_top_n)
    parser.add_argument("--out", default=None, help="write full per-question results to this JSON file")
    args = parser.parse_args()

    summary, rows = evaluate(args.golden, args.k)

    print("\n=== Retrieval eval summary ===")
    for key, value in summary.items():
        print(f"{key:>24}: {value}")

    failures = [
        r for r in rows
        if (r["kind"] == "answerable" and not r["hit_at_k"])
        or (r["kind"] == "abstention" and not r["abstained_correctly"])
    ]
    if failures:
        print(f"\n--- {len(failures)} failing case(s) ---")
        for r in failures:
            print(f"  [{r['kind']}] {r['question']}  (returned={r['returned']}, top_score={r['top_score']})")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "rows": rows}, f, indent=2, ensure_ascii=False)
        print(f"\nFull results written to {args.out}")


if __name__ == "__main__":
    main()
