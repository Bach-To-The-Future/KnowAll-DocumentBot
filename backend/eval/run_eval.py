"""Retrieval evaluation against the golden set.

Runs IN-PROCESS (services must be up and the corpus ingested):

    docker compose exec api python eval/run_eval.py --mode retrieval
    docker compose exec -e ENABLE_ANSWER_CACHE=false api \
        python eval/run_eval.py --mode full --runs 3

TWO MODES, and they are not comparable to each other (the comparator treats
`eval_mode` as a hard field):

  retrieval  Calls RetrievalService directly. NO LLM anywhere in the loop:
             no query rewrite, no multi-query expansion, no generation, no
             answer cache. Fully deterministic — CI tolerance is ZERO.
             This is the mode that gates every PR touching extraction,
             services, integrations or core/config.py.

  full       Goes through QueryService.prepare(), so rewrite and expansion
             run against the real LLM. Non-deterministic; the tolerance is a
             MEASURED number (see --runs). Nightly, and on demand before
             merging changes to query.py or retrieval.py.
             Requires ENABLE_ANSWER_CACHE=false — refuses to run otherwise,
             because runs 2 and 3 would hit cache and report near-zero
             variance that is an artifact of the cache, not a property of
             the system.

REPORTING
  Metrics are reported PER TIER and never averaged across tiers. Tier B is
  deliberately adversarial synthetic content; folding it into a headline
  number next to real documents produces a figure that means nothing.
  `slices` (category, language, lexical overlap) is diagnostic — it is
  recorded and printed, but the comparator gates on tiers only.

METRICS
  recall@fetch             answerable queries with >=1 relevant chunk in the
                           pooled pre-rerank candidates (the retrieval ceiling)
  hit@k                    answerable queries with a relevant chunk in the
                           final top-k
  mrr@k                    mean reciprocal rank of the first relevant chunk
  false_abstention_rate    ANSWERABLE queries that returned nothing.
                           LOWER IS BETTER.
  correct_abstention_rate  UNANSWERABLE queries that returned nothing.
                           HIGHER IS BETTER.

The abstention split is not cosmetic. A single "abstention_accuracy" measured
over unanswerable entries alone reported 1.000 on a run that abstained on 15
of 22 ANSWERABLE questions — it improves as the system stops answering, so it
cannot gate a change to the score floor. The two rates move in opposite
directions under that change, which is the whole point of separating them.

A chunk is "relevant" when its source is in expected_sources AND (keywords
empty OR any keyword appears in its text, case-insensitively).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import Settings, get_settings  # noqa: E402
from core.model_identity import verify_embedding_model  # noqa: E402
from eval import provenance  # noqa: E402
from eval.corpus import verify as corpus_verify  # noqa: E402
from models.schemas import QueryRequest  # noqa: E402
from services.query import QueryService  # noqa: E402

RETRIEVAL_MODE = provenance.RETRIEVAL_MODE
FULL_MODE = provenance.FULL_MODE

# Closed vocabulary. An unrecognised tag is a typo that would silently create a
# one-entry slice nobody looks at, so the loader rejects it.
CATEGORIES = frozenset({
    "plain-fact", "table-answer", "ocr-answer", "multi-hop", "cross-doc",
    "long-table-tail", "conversational", "unanswerable",
})

# Words too common to say anything about lexical overlap between a question and
# the text that answers it.
_STOPWORDS = frozenset("""
a an the of to in on at for from by with and or is are was were be been being do
does did what which who whom whose when where why how many much this that these
those it its as into than then there here not no if can could should would will
shall may might must have has had i you he she we they il elle ils elles le la
les un une des du de au aux et ou est sont dans sur pour par avec quel quelle
quels quelles combien quand comment pourquoi ce cet cette ces qui que quoi ne
pas plus
""".split())


def _tokens(text: str) -> set[str]:
    out: set[str] = set()
    word: list[str] = []
    for ch in text.lower():
        if ch.isalnum():
            word.append(ch)
        elif word:
            out.add("".join(word))
            word = []
    if word:
        out.add("".join(word))
    return {w for w in out if w not in _STOPWORDS and len(w) > 1}


def lexical_overlap(question: str, answer_snippet: str) -> float:
    """Fraction of the question's content words that also appear in the text
    that answers it.

    Computed from the GOLDEN FILE, not from retrieval output: it must be a
    stable property of the question so the slice means the same thing across
    runs. A low value is a question that cannot be answered by term matching —
    which is what a dense retriever is supposed to be for, and what BM25 alone
    will miss."""
    q = _tokens(question)
    if not q:
        return 0.0
    return len(q & _tokens(answer_snippet)) / len(q)


LOW_OVERLAP_THRESHOLD = 0.34


# --------------------------------------------------------------------------
# golden set
# --------------------------------------------------------------------------

def validate_golden(entries: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    for i, e in enumerate(entries):
        where = f"entry {i} ({str(e.get('question', '<no question>'))[:50]!r})"
        for field in ("question", "language", "answerable", "tier", "category"):
            if field not in e:
                problems.append(f"{where}: missing required field {field!r}")
        if e.get("tier") not in ("a", "b"):
            problems.append(f"{where}: tier must be 'a' or 'b', got {e.get('tier')!r}")
        if e.get("category") not in CATEGORIES:
            problems.append(f"{where}: unknown category {e.get('category')!r}; "
                            f"allowed: {sorted(CATEGORIES)}")
        if e.get("answerable"):
            if not e.get("expected_sources"):
                problems.append(f"{where}: answerable entries need expected_sources")
            if not e.get("answer_snippet"):
                problems.append(
                    f"{where}: answerable entries need answer_snippet (verbatim "
                    f"source text; it defines the lexical-overlap slice)")
        elif e.get("category") != "unanswerable":
            problems.append(f"{where}: answerable=false must be category 'unanswerable'")
        for turn in e.get("history", []):
            if "question" not in turn or "answer" not in turn:
                problems.append(f"{where}: history turns need 'question' and 'answer'")
    return problems


def load_golden(path: str) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        entries = json.load(fh)["entries"]
    problems = validate_golden(entries)
    if problems:
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(f"golden set {path} is invalid ({len(problems)} problem(s)).")
    return entries


def is_relevant(text: str, source: str, entry: dict) -> bool:
    if source not in entry["expected_sources"]:
        return False
    keywords = entry.get("expected_keywords") or []
    if not keywords:
        return True
    lowered = text.lower()
    return any(k.lower() in lowered for k in keywords)


# --------------------------------------------------------------------------
# one pass over the golden set
# --------------------------------------------------------------------------

def _retrieve_retrieval_mode(container: Any, entry: dict, k: int) -> tuple[list, list, dict]:
    """Deterministic path: the question verbatim, straight to retrieval."""
    q = entry["question"]
    candidates = (container.retrieval.fetch_candidates(q, filters=None)
                  if entry["answerable"] else [])
    chunks = container.retrieval.retrieve(q, filters=None, k=k)
    # needs_rewrite() is pure, so its verdict is recorded even here. The point
    # is to detect the regex OVER-TRIGGERING, and that is worth watching in the
    # mode whose numbers are stable. Nothing acts on it in this mode.
    return candidates, chunks, {
        "rewrite_would_fire": QueryService.needs_rewrite(q, entry.get("history", [])),
        "rewrite_fired": False,
        "standalone_question": q,
    }


def _retrieve_full_mode(container: Any, entry: dict, k: int,
                        session_id: str) -> tuple[list, list, dict]:
    """Through QueryService.prepare(): rewrite + expansion in the loop.

    History is seeded into real session memory rather than passed directly, so
    the code path exercised is the one production takes.
    """
    q = entry["question"]
    container.memory.clear_session(session_id)
    for turn in entry.get("history", []):
        container.memory.append_turn(session_id, turn["question"], turn["answer"])

    would_fire = QueryService.needs_rewrite(q, container.memory.get_history(session_id))
    prepared = container.query.prepare(
        QueryRequest(question=q, documents=None, session_id=session_id)
    )
    container.memory.clear_session(session_id)

    standalone = prepared.trace.get("standalone_question", q)
    chunks = prepared.citations[:k]
    # prepare() does not expose the pre-rerank pool, so recall@fetch is measured
    # against the REWRITTEN question — the same query the final ranking saw.
    candidates = (container.retrieval.fetch_candidates(standalone, filters=None)
                  if entry["answerable"] else [])
    return candidates, chunks, {
        "rewrite_would_fire": would_fire,
        "rewrite_fired": standalone != q,
        "standalone_question": standalone,
        "expanded_queries": prepared.trace.get("expanded_queries", []),
    }


def _chunk_view(chunk: Any) -> tuple[str, str, float | None]:
    """prepare() yields citation dicts; retrieve() yields chunk objects."""
    if isinstance(chunk, dict):
        return chunk["text"], chunk["source"], chunk.get("score")
    return chunk.text, chunk.source, chunk.score


def run_pass(container: Any, entries: list[dict], k: int, mode: str) -> list[dict]:
    rows: list[dict] = []
    for i, entry in enumerate(entries):
        if mode == FULL_MODE:
            candidates, chunks, meta = _retrieve_full_mode(
                container, entry, k, session_id=f"eval-{mode}-{i}"
            )
        else:
            candidates, chunks, meta = _retrieve_retrieval_mode(container, entry, k)

        row: dict[str, Any] = {
            "question": entry["question"],
            "language": entry["language"],
            "tier": entry["tier"],
            "category": entry["category"],
            "has_history": bool(entry.get("history")),
            "returned": len(chunks),
            **meta,
        }
        if entry.get("expects_rewrite") is not None:
            row["expects_rewrite"] = entry["expects_rewrite"]
            row["rewrite_branch_ok"] = (
                meta["rewrite_would_fire"] == entry["expects_rewrite"]
            )

        if entry["answerable"]:
            overlap = lexical_overlap(entry["question"], entry["answer_snippet"])
            views = [_chunk_view(c) for c in chunks]
            first_rank = next(
                (rank for rank, (text, source, _) in enumerate(views, 1)
                 if is_relevant(text, source, entry)),
                None,
            )
            row.update({
                "kind": "answerable",
                # An answerable question that returned nothing. This is the
                # user-facing failure: the system said "I don't know" about
                # something the corpus answers.
                "falsely_abstained": len(chunks) == 0,
                "lexical_overlap": round(overlap, 3),
                "low_overlap": overlap < LOW_OVERLAP_THRESHOLD,
                "recall_at_fetch": any(
                    is_relevant(c.text, c.payload.get("source", ""), entry)
                    for c in candidates
                ),
                "hit_at_k": first_rank is not None,
                "reciprocal_rank": (1.0 / first_rank) if first_rank else 0.0,
                "top_score": views[0][2] if views else None,
            })
        else:
            row.update({
                "kind": "abstention",
                "abstained_correctly": len(chunks) == 0,
                "top_score": _chunk_view(chunks[0])[2] if chunks else None,
            })
        rows.append(row)
    return rows


# --------------------------------------------------------------------------
# aggregation
# --------------------------------------------------------------------------

def _rate(items: list[dict], key: str) -> float | None:
    return round(sum(1 for i in items if i[key]) / len(items), 3) if items else None


def metrics_for(rows: list[dict]) -> dict[str, Any]:
    answerable = [r for r in rows if r["kind"] == "answerable"]
    abstention = [r for r in rows if r["kind"] == "abstention"]
    return {
        "n_answerable": len(answerable),
        "n_abstention": len(abstention),
        "recall_at_fetch": _rate(answerable, "recall_at_fetch"),
        "hit_at_k": _rate(answerable, "hit_at_k"),
        "mrr_at_k": (round(sum(r["reciprocal_rank"] for r in answerable) / len(answerable), 3)
                     if answerable else None),
        # Two populations, two numbers. Merging them lets a system that answers
        # nothing score perfectly.
        "false_abstention_rate": _rate(answerable, "falsely_abstained"),
        "correct_abstention_rate": _rate(abstention, "abstained_correctly"),
    }


def summarize(rows: list[dict]) -> dict[str, Any]:
    """Per-tier headline metrics (gated) plus diagnostic slices (not gated)."""
    results = {
        f"tier_{tier}": metrics_for([r for r in rows if r["tier"] == tier])
        for tier in sorted({r["tier"] for r in rows})
    }

    answerable = [r for r in rows if r["kind"] == "answerable"]

    def bucket(buckets: dict[str, list[dict]]) -> dict[str, Any]:
        return {label: metrics_for(rs) for label, rs in buckets.items() if rs}

    slices: dict[str, Any] = {
        "category": bucket({c: [r for r in rows if r["category"] == c]
                            for c in sorted({r["category"] for r in rows})}),
        "language": bucket({lang: [r for r in rows if r["language"] == lang]
                            for lang in sorted({r["language"] for r in rows})}),
        # The slice that says whether dense retrieval is earning its keep:
        # questions whose wording does NOT appear in the text that answers them.
        "lexical_overlap": bucket({
            "low": [r for r in answerable if r["low_overlap"]],
            "high": [r for r in answerable if not r["low_overlap"]],
        }),
    }

    branch_rows = [r for r in rows if "rewrite_branch_ok" in r]
    rewrite = {
        "n_would_fire": sum(1 for r in rows if r["rewrite_would_fire"]),
        "n_fired": sum(1 for r in rows if r["rewrite_fired"]),
        "n_branch_asserted": len(branch_rows),
        "branch_mismatches": [
            {"question": r["question"], "expected": r["expects_rewrite"],
             "actual": r["rewrite_would_fire"]}
            for r in branch_rows if not r["rewrite_branch_ok"]
        ],
    }
    return {"results": results, "slices": slices, "rewrite": rewrite}


def variance_report(per_run: list[dict[str, Any]]) -> dict[str, Any]:
    """Spread across repeated runs. In retrieval mode this must be exactly
    zero; anything else is a source of nondeterminism we have not found."""
    report: dict[str, Any] = {}
    for tier in sorted({t for run in per_run for t in run}):
        for metric in ("recall_at_fetch", "hit_at_k", "mrr_at_k",
                       "false_abstention_rate", "correct_abstention_rate"):
            values = [run[tier][metric] for run in per_run
                      if tier in run and run[tier].get(metric) is not None]
            if len(values) < 2:
                continue
            report[f"{tier}.{metric}"] = {
                "values": values,
                "min": min(values),
                "max": max(values),
                "spread": round(max(values) - min(values), 4),
                "stdev": round(statistics.stdev(values), 4),
            }
    if report:
        report["max_spread"] = max(v["spread"] for v in report.values()
                                   if isinstance(v, dict))
    return report


# --------------------------------------------------------------------------
# entrypoint
# --------------------------------------------------------------------------

def gate_full_mode(settings: Settings) -> None:
    if settings.enable_answer_cache:
        sys.exit(
            "REFUSING to run full mode with the answer cache ENABLED.\n"
            "  Runs 2..N would be served from Redis and report a variance of\n"
            "  ~0 that is a property of the cache, not of the system. Re-run\n"
            "  with ENABLE_ANSWER_CACHE=false."
        )


def main() -> int:
    from services.container import build_container

    here = os.path.dirname(__file__)
    parser = argparse.ArgumentParser(description="Evaluate retrieval against the golden set.")
    parser.add_argument("--mode", choices=[RETRIEVAL_MODE, FULL_MODE], default=RETRIEVAL_MODE)
    parser.add_argument("--golden", default=os.path.join(here, "golden_set.json"))
    parser.add_argument("--k", type=int, default=None)
    parser.add_argument("--runs", type=int, default=1,
                        help="repeat the pass N times and report the spread "
                             "(this is how the full-mode tolerance is measured)")
    parser.add_argument("--tier", choices=["a", "b"], default=None,
                        help="restrict to one tier")
    parser.add_argument("--out", default=None, help="write the baseline JSON here")
    parser.add_argument("--tolerance", type=float, default=None,
                        help="record this tolerance in the baseline for compare.py")
    args = parser.parse_args()

    settings = get_settings()
    k = args.k if args.k is not None else settings.rerank_top_n

    # Three gates, all before a single query runs. Each one, if skipped, yields
    # numbers that look fine and mean nothing.
    if corpus_verify.verify() != 0:
        return 2
    embed_digest = verify_embedding_model(settings, context="eval")
    if args.mode == FULL_MODE:
        gate_full_mode(settings)

    entries = load_golden(args.golden)
    if args.tier:
        entries = [e for e in entries if e["tier"] == args.tier]
        if not entries:
            print(f"no golden entries in tier {args.tier}", file=sys.stderr)
            return 2

    container = build_container(settings)

    per_run_results: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    rows: list[dict] = []
    for run in range(args.runs):
        rows = run_pass(container, entries, k, args.mode)
        summary = summarize(rows)
        per_run_results.append(summary["results"])
        if args.runs > 1:
            print(f"run {run + 1}/{args.runs}: " + json.dumps(
                {t: m["hit_at_k"] for t, m in summary["results"].items()}))

    baseline: dict[str, Any] = {
        "eval_mode": args.mode,
        "k": k,
        "provenance": provenance.build(
            settings,
            corpus_manifest_sha256=corpus_verify.manifest_hash(),
            embed_model_digest=embed_digest,
            eval_mode=args.mode,
        ),
        "results": summary["results"],
        "slices": summary["slices"],
        "rewrite": summary["rewrite"],
        "rows": rows,
    }
    if args.tolerance is not None:
        baseline["tolerance"] = args.tolerance
    if args.runs > 1:
        baseline["variance"] = variance_report(per_run_results)

    print(f"\n=== eval summary ({args.mode} mode, k={k}) ===")
    for tier, m in baseline["results"].items():
        print(f"[{tier}]  " + "  ".join(
            f"{key}={value}" for key, value in m.items() if value is not None))
    for slice_name, buckets in baseline["slices"].items():
        print(f"\n-- by {slice_name} --")
        for label, m in buckets.items():
            print(f"  {label:<18} hit@k={m['hit_at_k']}  mrr={m['mrr_at_k']}  "
                  f"false_abstain={m['false_abstention_rate']}  "
                  f"correct_abstain={m['correct_abstention_rate']}  "
                  f"n={m['n_answerable']}+{m['n_abstention']}")

    rw = baseline["rewrite"]
    print(f"\n-- rewrite --\n  would_fire={rw['n_would_fire']}  fired={rw['n_fired']}  "
          f"branch_asserted={rw['n_branch_asserted']}")
    if rw["branch_mismatches"]:
        print("  BRANCH MISMATCHES (needs_rewrite() disagrees with the golden set):")
        for m in rw["branch_mismatches"]:
            print(f"    expected={m['expected']} actual={m['actual']}  {m['question']}")

    if "variance" in baseline:
        print("\n-- variance across runs --")
        for key, v in baseline["variance"].items():
            if isinstance(v, dict):
                print(f"  {key:<28} spread={v['spread']}  stdev={v['stdev']}  {v['values']}")
        print(f"  MAX SPREAD: {baseline['variance'].get('max_spread')}")

    failures = [
        r for r in rows
        if (r["kind"] == "answerable" and not r["hit_at_k"])
        or (r["kind"] == "abstention" and not r["abstained_correctly"])
    ]
    if failures:
        print(f"\n--- {len(failures)} failing case(s) ---")
        for r in failures:
            print(f"  [{r['tier']}/{r['category']}] {r['question']}  "
                  f"(returned={r['returned']}, top_score={r['top_score']})")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(baseline, fh, indent=2, ensure_ascii=False)
        print(f"\nBaseline written to {args.out}")

    # Branch mismatches fail the run: an over-triggering rewrite regex is
    # exactly the silent change this harness exists to catch.
    return 1 if rw["branch_mismatches"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
