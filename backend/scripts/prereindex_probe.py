"""Pre-reindex diagnostic against the PRODUCTION collection.

    docker compose exec api python scripts/prereindex_probe.py

This is NOT a baseline and cannot become one: the documents behind
`knowall_collection` have no manifest and no checksums, so nothing measured here
is reproducible. It is taken because the information **disappears the moment the
reindex runs**, and because that collection has a different composition from
tier B — mostly prose, 376 points instead of 18.

Three questions it exists to answer:

  1. COVERAGE. The live golden set was authored against tier B and will not
     resolve here. The retired set (`golden_set.legacy.json`) was authored
     against these documents. Report honestly how much of it resolves.
  2. Does finding #27's TABLE-ANSWER SIGNATURE reproduce on a prose-heavy
     corpus? If it does it is a system property; if not it may be a tier-B
     artifact, which changes what Phase 1A has to test.
  3. Does finding #31's NEAR-MISS behaviour reproduce? Same reasoning.

Plus `recall_at_fetch` at 376 points, which is a real measurement for the first
time — at 18 chunks against `fetch_k=20` it was arithmetic.
"""
from __future__ import annotations

import json
import logging
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.disable(logging.INFO)

from core.config import get_settings  # noqa: E402
from eval.diagnose_rerank import classify_shape  # noqa: E402
from eval.run_eval import is_relevant  # noqa: E402
from services.container import build_container  # noqa: E402

# Near-miss probes authored against THESE documents: each is squarely on a topic
# the corpus covers, and asks for a specific the corpus does not contain.
NEAR_MISS = [
    "Which Hadoop component replaced MapReduce in later releases?",
    "What is the maximum number of nodes in a Databricks interactive cluster?",
    "What is the correlation coefficient between TV and newspaper advertising spend?",
    "What is the pass mark for the ABC DELF junior A2 exam?",
]


def main() -> int:
    settings = get_settings()
    container = build_container(settings)
    store = container.vector_store
    client = store._get_client()
    collection = settings.qdrant_collection

    total = client.count(collection).count
    points, _ = client.scroll(collection, limit=10_000,
                              with_payload=["source"], with_vectors=False)
    sources = {(p.payload or {}).get("source") for p in points}
    print(f"collection            : {collection}")
    print(f"points                : {total}")
    print(f"distinct sources      : {len(sources)}")
    print(f"abstention_score_floor: {settings.abstention_score_floor}")
    print(f"rerank_score_floor    : {settings.rerank_score_floor}")
    print(f"retrieval_fetch_k     : {settings.retrieval_fetch_k}\n")

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    legacy = json.load(open(os.path.join(here, "eval", "golden_set.legacy.json"),
                            encoding="utf-8"))["entries"]

    # ---- 1. coverage -----------------------------------------------------
    resolvable, unresolvable = [], []
    for e in legacy:
        if not e["answerable"]:
            continue
        if all(s in sources for s in e["expected_sources"]):
            resolvable.append(e)
        else:
            unresolvable.append(e)
    print("=== 1. COVERAGE ===")
    print(f"  legacy answerable entries : {len(resolvable) + len(unresolvable)}")
    print(f"  resolvable here           : {len(resolvable)}")
    if unresolvable:
        print(f"  NOT resolvable            : {len(unresolvable)}")
        for e in unresolvable:
            missing = [s for s in e["expected_sources"] if s not in sources]
            print(f"     missing {missing}: {e['question'][:50]}")
    print()

    if not resolvable:
        print("Nothing resolvable — cannot probe.", file=sys.stderr)
        return 1

    # ---- 2. retrieval metrics + F27 signature ----------------------------
    k = settings.rerank_top_n
    rows = []
    for e in resolvable:
        q = e["question"]
        cands = [c for c in container.retrieval.fetch_candidates(q, filters=None)
                 if c.text.strip()]
        pre_hit = any(is_relevant(c.text, c.payload.get("source", ""), e) for c in cands)
        scores = container.reranker.scores(q, [c.text for c in cands])
        ranked = sorted(zip(scores, cands, strict=True), key=lambda x: x[0], reverse=True)
        top_score, top_cand = ranked[0]
        chunks = container.retrieval.retrieve(q, filters=None, k=k)
        rank = next((i for i, c in enumerate(chunks, 1)
                     if is_relevant(c.text, c.source, e)), None)
        rows.append({
            "q": q, "recall": pre_hit, "hit": rank is not None,
            "rr": (1.0 / rank) if rank else 0.0, "returned": len(chunks),
            "top_score": float(top_score),
            "top_shape": classify_shape(top_cand.text, top_cand.payload),
            "top_correct": is_relevant(top_cand.text,
                                       top_cand.payload.get("source", ""), e),
            "n_cands": len(cands),
        })

    def rate(key):
        return round(sum(1 for r in rows if r[key]) / len(rows), 3)

    print("=== 2. RETRIEVAL on a 376-point, prose-heavy corpus ===")
    print(f"  n                     : {len(rows)}")
    print(f"  recall_at_fetch       : {rate('recall')}   <- REAL now, not arithmetic")
    print(f"  hit_at_k              : {rate('hit')}")
    print(f"  mrr_at_k              : {round(sum(r['rr'] for r in rows) / len(rows), 3)}")
    print(f"  false_abstention_rate : {round(sum(1 for r in rows if r['returned'] == 0) / len(rows), 3)}")
    print(f"  mean candidates/query : {round(statistics.mean(r['n_cands'] for r in rows), 1)}"
          f"  (tier B returned the whole corpus)")
    print()

    print("=== F27 TABLE-ANSWER SIGNATURE — top-1 rerank score by chunk shape ===")
    for shape in ("prose", "table", "list"):
        subset = [r for r in rows if r["top_shape"] == shape]
        if not subset:
            continue
        vals = sorted(r["top_score"] for r in subset)
        cut_at_025 = sum(1 for v in vals if v < 0.25)
        print(f"  {shape:<6} n={len(vals):<3} min={vals[0]:.4f} "
              f"median={statistics.median(vals):.4f} max={vals[-1]:.4f}"
              f"   below the OLD 0.25 floor: {cut_at_025}/{len(vals)}")
    print("\n  per-entry:")
    for r in sorted(rows, key=lambda r: r["top_score"]):
        flag = "" if r["top_score"] >= 0.25 else "   <- would have been CUT by the old floor"
        print(f"    {r['top_score']:.4f} {r['top_shape']:<6} "
              f"{'ok ' if r['top_correct'] else 'BAD'} {r['q'][:52]}{flag}")

    # ---- 3. F31 near-miss ------------------------------------------------
    print("\n=== 3. F31 NEAR-MISS on real documents ===")
    for q in NEAR_MISS:
        cands = [c for c in container.retrieval.fetch_candidates(q, filters=None)
                 if c.text.strip()]
        if not cands:
            print(f"  no candidates: {q}")
            continue
        scores = container.reranker.scores(q, [c.text for c in cands])
        ranked = sorted(zip(scores, cands, strict=True), key=lambda x: x[0], reverse=True)
        top, cand = ranked[0]
        chunks = container.retrieval.retrieve(q, filters=None, k=k)
        verdict = "ABSTAINED" if not chunks else f"returned {len(chunks)}"
        print(f"  top={float(top):.4f} {verdict:<12} {q}")
        print(f"       best chunk: {cand.payload.get('source')} "
              f"{cand.text[:90]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
