"""Finding #27 diagnostics: what the cross-encoder actually receives, and what
its scores actually separate.

Two questions, neither answerable by reading the code, both answerable before
tier A exists:

  1. INPUT. Heading paths are prepended at extraction time and context
     expansion runs AFTER reranking. So does the cross-encoder score the
     enriched text the embedding leg saw, or a bare fragment? If it is scoring
     a bare table row with no section title, a low score is a defect in what we
     hand it, not a threshold to tune.

  2. SEPARATION. Group scores by chunk SHAPE (table/list vs prose) and by
     whether the chunk is the correct answer, and measure the rank1 - rank2
     gap. An absolute floor throws the gap away; if the gap separates correct
     from incorrect where the absolute value does not, a rank-aware criterion
     is available and the floor is the wrong instrument.

    docker compose exec -e QDRANT_COLLECTION=knowall_eval api \
        python eval/diagnose_rerank.py --out /tmp/rerank_diag.json

Reports only. Changes nothing, tunes nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import get_settings  # noqa: E402
from eval.run_eval import is_relevant, load_golden  # noqa: E402


def classify_shape(text: str, payload: dict[str, Any]) -> str:
    """table / list / prose, from the chunk itself.

    Deliberately crude and explicit rather than trusting a metadata flag that
    may not be set on every path: the question is what the CROSS-ENCODER sees,
    and it sees the text.
    """
    if payload.get("is_table") or payload.get("chunk_type") == "table":
        return "table"
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return "prose"
    delimited = sum(1 for ln in lines if ln.count(",") >= 2 or ln.count("|") >= 2
                    or ln.count("\t") >= 1)
    if delimited >= max(2, len(lines) // 2):
        return "table"
    words_per_line = statistics.mean(len(ln.split()) for ln in lines)
    if len(lines) >= 3 and words_per_line < 8:
        return "list"
    return "prose"


def describe_input(text: str, payload: dict[str, Any]) -> dict[str, Any]:
    """What did the reranker actually get handed?"""
    section = payload.get("section_title")
    first_line = text.split("\n", 1)[0].strip()
    # Extractors emit "<heading path>\n\n<body>", so a section title present in
    # metadata AND leading the text means the enrichment survived into the
    # stored chunk. Present in metadata but absent from the text means the
    # cross-encoder is scoring a bare fragment.
    return {
        "section_title": section,
        "has_section_metadata": bool(section),
        "text_starts_with_section": bool(section) and text.lstrip().startswith(str(section)),
        "first_line": first_line[:100],
        "chars": len(text),
    }


def main() -> int:
    from services.container import build_container

    here = os.path.dirname(__file__)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden", default=os.path.join(here, "golden_set.json"))
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    settings = get_settings()
    floor = settings.rerank_score_floor
    entries = [e for e in load_golden(args.golden) if e["answerable"]]
    container = build_container(settings)

    per_query: list[dict[str, Any]] = []
    per_candidate: list[dict[str, Any]] = []

    for entry in entries:
        q = entry["question"]
        candidates = [c for c in container.retrieval.fetch_candidates(q, filters=None)
                      if c.text.strip()]
        if not candidates:
            continue
        scores = container.reranker.scores(q, [c.text for c in candidates])
        ranked = sorted(zip(scores, candidates, strict=True),
                        key=lambda item: item[0], reverse=True)

        for rank, (score, cand) in enumerate(ranked, 1):
            payload = cand.payload
            correct = is_relevant(cand.text, payload.get("source", ""), entry)
            per_candidate.append({
                "question": q,
                "category": entry["category"],
                "rank": rank,
                "score": round(float(score), 6),
                "correct": correct,
                "source": payload.get("source"),
                "shape": classify_shape(cand.text, payload),
                "input": describe_input(cand.text, payload),
            })

        top_score, top_cand = ranked[0]
        second = float(ranked[1][0]) if len(ranked) > 1 else 0.0
        top_correct = is_relevant(top_cand.text, top_cand.payload.get("source", ""), entry)
        per_query.append({
            "question": q,
            "category": entry["category"],
            "top_score": round(float(top_score), 6),
            "second_score": round(second, 6),
            "abs_gap": round(float(top_score) - second, 6),
            "ratio_gap": round(float(top_score) / second, 2) if second > 0 else None,
            "top_is_correct": top_correct,
            "top_shape": classify_shape(top_cand.text, top_cand.payload),
            "passes_floor": float(top_score) >= floor,
            "n_candidates": len(candidates),
        })

    # ---- report ----------------------------------------------------------
    print(f"\n=== rank-1 behaviour (floor = {floor}) ===")
    print(f"{'top':>8} {'2nd':>9} {'ratio':>9}  {'ok':<3} {'floor':<6} {'shape':<6} question")
    for r in per_query:
        print(f"{r['top_score']:>8.4f} {r['second_score']:>9.4f} "
              f"{(str(r['ratio_gap']) + 'x' if r['ratio_gap'] else '  inf'):>9}  "
              f"{'Y' if r['top_is_correct'] else 'N':<3} "
              f"{'pass' if r['passes_floor'] else 'CUT':<6} {r['top_shape']:<6} "
              f"{r['question'][:52]}")

    correct_top = [r for r in per_query if r["top_is_correct"]]
    wrong_top = [r for r in per_query if not r["top_is_correct"]]

    def stat(rows: list[dict], key: str) -> str:
        vals = [r[key] for r in rows if r[key] is not None]
        if not vals:
            return "n/a"
        return (f"n={len(vals)} min={min(vals):.4f} median={statistics.median(vals):.4f} "
                f"max={max(vals):.4f}")

    print("\n=== does the ABSOLUTE score separate correct from incorrect? ===")
    print(f"  rank-1 correct   top_score  {stat(correct_top, 'top_score')}")
    print(f"  rank-1 incorrect top_score  {stat(wrong_top, 'top_score')}")

    print("\n=== does the GAP separate them? ===")
    print(f"  rank-1 correct   ratio_gap  {stat(correct_top, 'ratio_gap')}")
    print(f"  rank-1 incorrect ratio_gap  {stat(wrong_top, 'ratio_gap')}")

    print("\n=== absolute score by shape, correct rank-1 chunks only ===")
    for shape in ("prose", "table", "list"):
        rows = [r for r in correct_top if r["top_shape"] == shape]
        cut = sum(1 for r in rows if not r["passes_floor"])
        print(f"  {shape:<6} {stat(rows, 'top_score')}   cut by floor: {cut}/{len(rows)}")

    print("\n=== what the cross-encoder was handed ===")
    rank1 = [c for c in per_candidate if c["rank"] == 1]
    with_meta = [c for c in rank1 if c["input"]["has_section_metadata"]]
    enriched = [c for c in with_meta if c["input"]["text_starts_with_section"]]
    print(f"  rank-1 chunks:                       {len(rank1)}")
    print(f"  ... carrying section_title metadata: {len(with_meta)}")
    print(f"  ... whose TEXT leads with it:        {len(enriched)}")
    bare = [c for c in with_meta if not c["input"]["text_starts_with_section"]]
    if bare:
        print("  BARE (metadata present, text does NOT carry it) — the reranker is")
        print("  scoring a fragment the embedding leg never saw:")
        for c in bare[:8]:
            print(f"    {c['source']:<28} section={c['input']['section_title']!r}")
            print(f"      first line: {c['input']['first_line']!r}")
    no_meta = [c for c in rank1 if not c["input"]["has_section_metadata"]]
    if no_meta:
        print(f"  no section metadata at all:          {len(no_meta)}")
        for c in no_meta[:8]:
            print(f"    {c['source']:<28} shape={c['shape']:<6} "
                  f"first line: {c['input']['first_line']!r}")

    print("\n=== keep-criterion comparison (rank-1 only, no knob changed) ===")
    for label, keep in (
        (f"absolute floor >= {floor}", lambda r: r["top_score"] >= floor),
        ("ratio gap >= 5x", lambda r: (r["ratio_gap"] or float("inf")) >= 5),
        ("ratio gap >= 10x", lambda r: (r["ratio_gap"] or float("inf")) >= 10),
        ("abs gap >= 0.01", lambda r: r["abs_gap"] >= 0.01),
    ):
        kept_correct = sum(1 for r in correct_top if keep(r))
        kept_wrong = sum(1 for r in wrong_top if keep(r))
        print(f"  {label:<24} keeps {kept_correct}/{len(correct_top)} correct, "
              f"{kept_wrong}/{len(wrong_top)} incorrect")
    print("\n  (Rank-1-incorrect rows are NOT the unanswerable set — those are")
    print("   excluded above. Abstention behaviour must be measured separately")
    print("   with false_abstention_rate / correct_abstention_rate.)")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump({"floor": floor, "per_query": per_query,
                       "per_candidate": per_candidate}, fh, indent=2, ensure_ascii=False)
        print(f"\nWritten to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
