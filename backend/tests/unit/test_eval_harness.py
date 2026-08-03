"""Harness invariants, and the golden set's own authoring rules as a CI gate.

The second half matters more than the first. "40% of answerable entries must
use vocabulary absent from the answering chunk" and "the conversational entries
must cover all four needs_rewrite() branches" are rules that decay silently the
moment someone adds an entry without reading the schema. Asserting them here is
what keeps them true.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.run_eval import (
    CATEGORIES,
    FULL_MODE,
    LOW_OVERLAP_THRESHOLD,
    gate_full_mode,
    lexical_overlap,
    metrics_for,
    summarize,
    validate_golden,
    variance_report,
)
from services.query import QueryService

GOLDEN_PATH = Path(__file__).resolve().parents[2] / "eval" / "golden_set.json"
GOLDEN = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["entries"]
ANSWERABLE = [e for e in GOLDEN if e["answerable"]]


# --------------------------------------------------------------------------
# lexical overlap
# --------------------------------------------------------------------------

def test_overlap_is_one_when_the_question_reuses_the_answer_wording() -> None:
    assert lexical_overlap(
        "What are records retained for?", "Records are retained for seven years."
    ) == 1.0


def test_overlap_is_zero_when_the_question_shares_no_content_words() -> None:
    assert lexical_overlap(
        "How long must files be kept?", "Records are retained for seven years."
    ) == 0.0


def test_stopwords_do_not_manufacture_overlap() -> None:
    # Nothing but function words in common: the score must stay at zero rather
    # than reporting a match on "the"/"is"/"of".
    assert lexical_overlap("What is the value of it?", "Badges are revoked.") == 0.0


def test_overlap_is_symmetric_in_case_and_punctuation() -> None:
    assert lexical_overlap("REORDER, point?", "the reorder point") == 1.0


# --------------------------------------------------------------------------
# golden set schema
# --------------------------------------------------------------------------

def test_committed_golden_set_validates() -> None:
    assert validate_golden(GOLDEN) == []


@pytest.mark.parametrize("mutation,expected_fragment", [
    ({"tier": "c"}, "tier must be"),
    ({"category": "made-up"}, "unknown category"),
    ({"answer_snippet": ""}, "answer_snippet"),
    ({"expected_sources": []}, "expected_sources"),
    ({"history": [{"question": "q"}]}, "history turns"),
])
def test_loader_rejects_malformed_entries(mutation: dict, expected_fragment: str) -> None:
    entry = dict(ANSWERABLE[0], **mutation)
    problems = validate_golden([entry])
    assert any(expected_fragment in p for p in problems), problems


def test_unanswerable_entries_must_be_tagged_unanswerable() -> None:
    entry = dict(ANSWERABLE[0], answerable=False)
    assert any("category 'unanswerable'" in p for p in validate_golden([entry]))


# --------------------------------------------------------------------------
# golden set authoring rules
# --------------------------------------------------------------------------

def test_at_least_40_percent_of_answerable_entries_have_low_lexical_overlap() -> None:
    """The corpus must not be answerable by term matching alone. If this drops
    below 40% the golden set has drifted toward questions that quote the
    document, and hit@k stops saying anything about dense retrieval."""
    low = [e for e in ANSWERABLE
           if lexical_overlap(e["question"], e["answer_snippet"]) < LOW_OVERLAP_THRESHOLD]
    ratio = len(low) / len(ANSWERABLE)
    assert ratio >= 0.40, f"only {len(low)}/{len(ANSWERABLE)} = {ratio:.0%} low-overlap"


def _branch(entry: dict) -> str:
    if not entry.get("history"):
        return "1-no-history"
    if len(entry["question"].split()) <= 6:
        return "2-short-circuit"
    return "3-anaphora" if entry["expects_rewrite"] else "4-long-no-anaphora"


def test_every_needs_rewrite_branch_is_covered() -> None:
    covered = {_branch(e) for e in GOLDEN if e["category"] == "conversational"}
    assert covered == {"1-no-history", "2-short-circuit", "3-anaphora",
                       "4-long-no-anaphora"}, covered


def test_the_skip_branch_has_both_an_english_and_a_french_negative() -> None:
    """Branch 4 is where a widened anaphora regex over-triggers first, and it
    over-triggers in one language before the other. Both must be pinned."""
    langs = {e["language"] for e in GOLDEN
             if e["category"] == "conversational" and _branch(e) == "4-long-no-anaphora"}
    assert langs == {"en", "fr"}, langs


def test_expects_rewrite_matches_the_real_needs_rewrite_for_every_entry() -> None:
    """This is the over-triggering alarm. Widening _ANAPHORA_RE turns some
    expects_rewrite=False entry True and fails here, in a unit test, instead of
    silently rewriting standalone questions in production."""
    wrong = [
        (e["question"], e["expects_rewrite"])
        for e in GOLDEN
        if e.get("expects_rewrite") is not None
        and QueryService.needs_rewrite(e["question"], e.get("history", []))
        != e["expects_rewrite"]
    ]
    assert wrong == []


def test_quelle_does_not_match_the_elle_anaphor() -> None:
    """Word-boundary regression guard: dropping \\b from _ANAPHORA_RE makes
    every French 'Quelle ...' question look elliptical."""
    history = [{"question": "q", "answer": "a"}]
    assert QueryService.needs_rewrite(
        "Quelle est la periode de preavis prevue au contrat ?", history
    ) is False


def test_categories_used_are_all_declared() -> None:
    assert {e["category"] for e in GOLDEN} <= CATEGORIES


def test_expected_sources_reference_real_corpus_files() -> None:
    corpus = Path(__file__).resolve().parents[2] / "eval" / "corpus"
    on_disk = {p.name for p in corpus.rglob("*") if p.is_file()}
    referenced = {s for e in GOLDEN for s in e.get("expected_sources", [])}
    assert referenced <= on_disk, referenced - on_disk


# --------------------------------------------------------------------------
# aggregation
# --------------------------------------------------------------------------

def _row(**kw):
    base = {"question": "q?", "tier": "b", "category": "plain-fact", "language": "en",
            "kind": "answerable", "low_overlap": True, "recall_at_fetch": True,
            "hit_at_k": True, "reciprocal_rank": 1.0, "rewrite_would_fire": False,
            "rewrite_fired": False}
    base.update(kw)
    return base


def test_tiers_are_reported_separately_and_never_merged() -> None:
    rows = [_row(tier="a", hit_at_k=True, reciprocal_rank=1.0),
            _row(tier="b", hit_at_k=False, reciprocal_rank=0.0)]
    results = summarize(rows)["results"]
    assert results["tier_a"]["hit_at_k"] == 1.0
    assert results["tier_b"]["hit_at_k"] == 0.0


def test_abstention_rate_ignores_answerable_rows() -> None:
    rows = [_row(), _row(kind="abstention", abstained_correctly=False)]
    m = metrics_for(rows)
    assert m["n_answerable"] == 1 and m["n_abstention"] == 1
    assert m["abstention_accuracy"] == 0.0 and m["hit_at_k"] == 1.0


def test_empty_slice_is_omitted_rather_than_reported_as_zero() -> None:
    slices = summarize([_row(low_overlap=True)])["slices"]
    assert "low" in slices["lexical_overlap"]
    assert "high" not in slices["lexical_overlap"]  # not a 0.0 that looks like a failure


def test_rewrite_branch_mismatch_is_surfaced() -> None:
    rows = [_row(rewrite_would_fire=True, expects_rewrite=False, rewrite_branch_ok=False)]
    rewrite = summarize(rows)["rewrite"]
    assert rewrite["n_branch_asserted"] == 1
    assert len(rewrite["branch_mismatches"]) == 1


# --------------------------------------------------------------------------
# variance
# --------------------------------------------------------------------------

def test_identical_runs_report_zero_spread() -> None:
    run = {"tier_b": {"hit_at_k": 0.8, "mrr_at_k": 0.7,
                      "recall_at_fetch": 0.9, "abstention_accuracy": 1.0}}
    report = variance_report([run, run, run])
    assert report["max_spread"] == 0.0


def test_spread_is_measured_per_tier_and_metric() -> None:
    runs = [
        {"tier_b": {"hit_at_k": 0.80, "mrr_at_k": 0.70,
                    "recall_at_fetch": None, "abstention_accuracy": None}},
        {"tier_b": {"hit_at_k": 0.72, "mrr_at_k": 0.70,
                    "recall_at_fetch": None, "abstention_accuracy": None}},
    ]
    report = variance_report(runs)
    assert report["tier_b.hit_at_k"]["spread"] == pytest.approx(0.08)
    assert report["tier_b.mrr_at_k"]["spread"] == 0.0
    assert "tier_b.recall_at_fetch" not in report  # None is absent, not zero
    assert report["max_spread"] == pytest.approx(0.08)


def test_single_run_reports_no_variance() -> None:
    assert variance_report([{"tier_b": {"hit_at_k": 0.8}}]) == {}


# --------------------------------------------------------------------------
# full-mode gate
# --------------------------------------------------------------------------

class _Settings:
    def __init__(self, enable_answer_cache: bool) -> None:
        self.enable_answer_cache = enable_answer_cache


def test_full_mode_refuses_to_run_with_the_answer_cache_enabled() -> None:
    """Without this, runs 2..N are served from Redis and the measured variance
    is a property of the cache, not the system."""
    with pytest.raises(SystemExit) as exc:
        gate_full_mode(_Settings(enable_answer_cache=True))  # type: ignore[arg-type]
    assert "ENABLE_ANSWER_CACHE=false" in str(exc.value)
    assert FULL_MODE == "full"


def test_full_mode_runs_with_the_cache_disabled() -> None:
    gate_full_mode(_Settings(enable_answer_cache=False))  # type: ignore[arg-type]
