"""Baseline comparator with four outcomes.

    COMPARABLE                       nothing drifted; diff the numbers.
    COMPARABLE_WITH_COSMETIC_DRIFT   git sha / image digest / model revision
                                     moved. No expected effect on retrieval,
                                     but named so it is on the record.
    COMPARABLE_WITH_SEMANTIC_DRIFT   a retrieval knob moved (fetch_k, top_n,
                                     score floor, context mode, expansion...).
                                     Same scale, but these change WHAT GETS
                                     RETRIEVED — so a delta must never be
                                     attributed to the change under test
                                     without this being visible. Not a hard
                                     refusal: comparing across a knob sweep is
                                     exactly what a sweep is for.
    INCOMPARABLE                     hard refusal, no metrics printed. Corpus
                                     manifest hash, embedding model identity,
                                     chunking config, or eval_mode differ. A
                                     "regression" across any of those is a
                                     category error, not a result.

Exit codes: 0 comparable and within tolerance · 1 regression · 2 incomparable.

Usage:
    python eval/compare.py baselines/old.json baselines/new.json
    python eval/compare.py old.json new.json --tolerance 0.03
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.provenance import FULL_MODE, classify_fields  # noqa: E402

COMPARABLE = "COMPARABLE"
COSMETIC = "COMPARABLE_WITH_COSMETIC_DRIFT"
SEMANTIC = "COMPARABLE_WITH_SEMANTIC_DRIFT"
INCOMPARABLE = "INCOMPARABLE"

# Metrics where a DROP is a regression.
HIGHER_IS_BETTER = ("recall_at_fetch", "hit_at_k", "mrr_at_k", "correct_abstention_rate")

# Metrics where a RISE is a regression. false_abstention_rate is the
# user-facing failure -- the system said "I don't know" about something the
# corpus answers -- and it moves in the OPPOSITE direction to
# correct_abstention_rate under any change to the score floor. Gating on only
# one of the pair would let a change that silences the system look like a win.
LOWER_IS_BETTER = ("false_abstention_rate",)

METRIC_ORDER = HIGHER_IS_BETTER + LOWER_IS_BETTER


def _diff(a: dict, b: dict, fields: tuple[str, ...]) -> list[tuple[str, Any, Any]]:
    return [(f, a.get(f), b.get(f)) for f in fields if a.get(f) != b.get(f)]


def classify(old_prov: dict, new_prov: dict) -> tuple[str, list, list, list]:
    """Field classes depend on eval_mode (llm_model is hard in full mode).

    The STRICTER of the two modes is used: if either side ran in full mode,
    llm_model is treated as hard. Otherwise a full-vs-retrieval comparison
    could slip through on the retrieval side's laxer rules — though eval_mode
    is itself hard, so such a pair is already INCOMPARABLE.
    """
    modes = {old_prov.get("eval_mode"), new_prov.get("eval_mode")}
    mode = FULL_MODE if FULL_MODE in modes else str(new_prov.get("eval_mode", "retrieval"))
    hard_fields, semantic_fields, cosmetic_fields = classify_fields(mode)

    hard = _diff(old_prov, new_prov, hard_fields)
    semantic = _diff(old_prov, new_prov, semantic_fields)
    cosmetic = _diff(old_prov, new_prov, cosmetic_fields)

    if hard:
        return INCOMPARABLE, hard, semantic, cosmetic
    if semantic:
        return SEMANTIC, hard, semantic, cosmetic
    if cosmetic:
        return COSMETIC, hard, semantic, cosmetic
    return COMPARABLE, hard, semantic, cosmetic


def _print_drift(title: str, rows: list[tuple[str, Any, Any]]) -> None:
    if not rows:
        return
    print(f"\n{title}")
    for field, left, right in rows:
        print(f"  {field}: {left} -> {right}")


def compare(old: dict, new: dict, tolerance: float) -> int:
    verdict, hard, semantic, cosmetic = classify(
        old.get("provenance", {}), new.get("provenance", {})
    )
    print(f"verdict: {verdict}")

    if verdict == INCOMPARABLE:
        print("\nREFUSING TO DIFF — these baselines do not measure the same thing:",
              file=sys.stderr)
        for field, left, right in hard:
            print(f"  {field}:\n      old: {left}\n      new: {right}", file=sys.stderr)
        print(
            "\nA metric delta across any of these is a different measurement, not a\n"
            "regression. Re-record the baseline under the new conditions instead of\n"
            "comparing across them.",
            file=sys.stderr,
        )
        return 2

    _print_drift("SEMANTIC DRIFT — these change what gets retrieved; do NOT attribute "
                 "the delta below to the change under test without accounting for them:",
                 semantic)
    _print_drift("cosmetic drift (no expected retrieval effect):", cosmetic)

    # Per tier: tier A and tier B are never averaged together.
    regressions: list[str] = []
    print()
    for tier in sorted(set(old.get("results", {})) | set(new.get("results", {}))):
        old_m = old.get("results", {}).get(tier, {})
        new_m = new.get("results", {}).get(tier, {})
        if not old_m or not new_m:
            print(f"[{tier}] present in only one baseline — skipped")
            continue
        print(f"[{tier}]")
        for metric in METRIC_ORDER:
            o, n = old_m.get(metric), new_m.get(metric)
            if o is None or n is None:
                continue
            delta = n - o
            # Sign of "bad" depends on the metric, not on the sign of the delta.
            regressed = (delta > tolerance if metric in LOWER_IS_BETTER
                         else delta < -tolerance)
            arrow = "v" if metric in LOWER_IS_BETTER else "^"
            flag = ""
            if regressed:
                flag = f"  <-- REGRESSION (tolerance {tolerance})"
                regressions.append(f"{tier}.{metric}: {o:.3f} -> {n:.3f} ({delta:+.3f})")
            print(f"  {arrow} {metric:<24} {o:>6.3f} -> {n:>6.3f}  ({delta:+.3f}){flag}")

    if regressions:
        print("\nFAIL — regressions beyond tolerance:", file=sys.stderr)
        for line in regressions:
            print(f"  {line}", file=sys.stderr)
        return 1

    print("\nOK — no metric regressed beyond tolerance.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old")
    parser.add_argument("new")
    parser.add_argument("--tolerance", type=float, default=None,
                        help="max tolerated drop; defaults to the value recorded "
                             "in the NEW baseline")
    args = parser.parse_args()

    old = json.loads(Path(args.old).read_text(encoding="utf-8"))
    new = json.loads(Path(args.new).read_text(encoding="utf-8"))
    tolerance = args.tolerance if args.tolerance is not None else new.get("tolerance")
    if tolerance is None:
        print("No --tolerance given and none recorded in the new baseline.", file=sys.stderr)
        return 2
    return compare(old, new, float(tolerance))


if __name__ == "__main__":
    raise SystemExit(main())
