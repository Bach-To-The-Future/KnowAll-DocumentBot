"""The comparator is the thing that stops a bad number being read as a result.

Each test below pins one classification decision. The interesting ones are the
conditional `llm_model` cases: the same field must be a hard refusal in full
mode and ignorable noise in retrieval mode, because in retrieval mode the LLM
never runs.
"""
from __future__ import annotations

import pytest

from eval.compare import (
    COMPARABLE,
    COSMETIC,
    INCOMPARABLE,
    SEMANTIC,
    classify,
    compare,
)
from eval.provenance import FULL_MODE, RETRIEVAL_MODE, classify_fields, fingerprint


def prov(**overrides: object) -> dict:
    base = {
        "corpus_manifest_sha256": "abc123",
        "embed_model": "nomic-embed-text",
        "embed_model_digest": "deadbeef",
        "chunk_size": 1000,
        "chunk_overlap": 150,
        "table_chunk_char_budget": 4000,
        "table_max_rows_per_chunk": 40,
        "eval_mode": RETRIEVAL_MODE,
        "n_answerable": 22,
        "n_unanswerable": 10,
        "reranker_model": "BAAI/bge-reranker-base",
        "retrieval_fetch_k": 40,
        "rerank_top_n": 5,
        "rerank_score_floor": 0.0,
        "retrieval_context_mode": "section",
        "neighbor_window": 1,
        "parent_char_budget": 6000,
        "enable_multi_query": False,
        "query_expansion_count": 3,
        "enable_answer_cache": True,
        "llm_model": "llama3.2:1b",
        "llm_model_digest": "not-applicable",
        "max_concurrent_queries": 4,
        "reranker_revision": "2cfc18c",
        "bm25_revision": "e499a1f",
        "git_sha": "1111111",
        "api_image_digest": "sha256:aaa",
        "web_image_digest": "sha256:bbb",
    }
    base.update(overrides)
    return base


def baseline(prov_: dict, **metrics: float) -> dict:
    return {"provenance": prov_, "results": {"tier_a": dict(metrics)}}


def test_identical_tuples_are_comparable() -> None:
    verdict, *_ = classify(prov(), prov())
    assert verdict == COMPARABLE


@pytest.mark.parametrize(
    "field,value",
    [
        ("corpus_manifest_sha256", "different"),
        ("embed_model", "mxbai-embed-large"),
        ("embed_model_digest", "cafe1234"),
        ("chunk_size", 800),
        ("chunk_overlap", 0),
        ("table_chunk_char_budget", 2000),
        ("table_max_rows_per_chunk", 10),
        ("eval_mode", FULL_MODE),
        ("n_answerable", 15),
        ("n_unanswerable", 3),
    ],
)
def test_hard_fields_refuse_comparison(field: str, value: object) -> None:
    verdict, hard, _, _ = classify(prov(), prov(**{field: value}))
    assert verdict == INCOMPARABLE
    assert [row[0] for row in hard] == [field]


def test_the_real_audit_regression_is_now_INCOMPARABLE() -> None:
    """The exact comparison that reported a false +0.185 improvement.

    2026-08-10: baseline n_answerable=22 vs run n_answerable=15 (seven
    history-bearing entries retagged full-mode-only and skipped in retrieval
    mode). The comparator printed "OK - no metric regressed" and showed
    hit_at_k 0.682 -> 0.867. Those are rates over different denominators.

    Third instance of one class in this engagement: a metric improving because
    its population got easier, not because the system did.
    """
    old = prov(n_answerable=22, n_unanswerable=10)
    new = prov(n_answerable=15, n_unanswerable=10)
    verdict, hard, _, _ = classify(old, new)
    assert verdict == INCOMPARABLE
    assert [row[0] for row in hard] == ["n_answerable"]


def test_an_unchanged_population_still_compares() -> None:
    """The control: the guard must not fire on every run.

    Without this, making n_answerable hard could refuse every comparison and
    still look like a working guard.
    """
    verdict, *_ = classify(
        prov(n_answerable=22, n_unanswerable=10),
        prov(n_answerable=22, n_unanswerable=10),
    )
    assert verdict == COMPARABLE


@pytest.mark.parametrize(
    "field,value",
    [
        ("retrieval_fetch_k", 80),
        ("rerank_top_n", 8),
        ("rerank_score_floor", 0.2),
        ("retrieval_context_mode", "neighbor"),
        ("neighbor_window", 2),
        ("parent_char_budget", 12000),
        ("enable_multi_query", True),
        ("query_expansion_count", 5),
        ("enable_answer_cache", False),
        ("reranker_model", "BAAI/bge-reranker-large"),
    ],
)
def test_retrieval_knobs_are_semantic_drift(field: str, value: object) -> None:
    verdict, _, semantic, _ = classify(prov(), prov(**{field: value}))
    assert verdict == SEMANTIC
    assert [row[0] for row in semantic] == [field]


@pytest.mark.parametrize(
    "field", ["git_sha", "api_image_digest", "web_image_digest",
              "reranker_revision", "bm25_revision"],
)
def test_build_identity_is_cosmetic_drift(field: str) -> None:
    verdict, _, _, cosmetic = classify(prov(), prov(**{field: "moved"}))
    assert verdict == COSMETIC
    assert [row[0] for row in cosmetic] == [field]


def test_llm_model_is_hard_in_full_mode() -> None:
    """Full mode puts the LLM in the retrieval path (rewrite + expansion), so a
    different generation model is a different system, not drift."""
    old = prov(eval_mode=FULL_MODE)
    new = prov(eval_mode=FULL_MODE, llm_model="qwen2.5:3b")
    verdict, hard, _, _ = classify(old, new)
    assert verdict == INCOMPARABLE
    assert [row[0] for row in hard] == ["llm_model"]


def test_llm_model_is_cosmetic_in_retrieval_mode() -> None:
    """Retrieval mode never calls the LLM, so its identity cannot have moved a
    single retrieval number."""
    verdict, _, _, cosmetic = classify(prov(), prov(llm_model="qwen2.5:3b"))
    assert verdict == COSMETIC
    assert [row[0] for row in cosmetic] == ["llm_model"]


def test_hard_outranks_semantic_and_cosmetic() -> None:
    verdict, hard, semantic, cosmetic = classify(
        prov(), prov(chunk_size=512, retrieval_fetch_k=80, git_sha="zzz")
    )
    assert verdict == INCOMPARABLE
    assert hard and semantic and cosmetic


def test_semantic_outranks_cosmetic() -> None:
    verdict, _, semantic, cosmetic = classify(
        prov(), prov(retrieval_fetch_k=80, git_sha="zzz")
    )
    assert verdict == SEMANTIC
    assert semantic and cosmetic


def test_incomparable_exits_two_and_prints_no_metrics(capsys) -> None:
    rc = compare(
        baseline(prov(), hit_at_k=0.90),
        baseline(prov(chunk_size=512), hit_at_k=0.10),
        tolerance=0.02,
    )
    captured = capsys.readouterr()
    assert rc == 2
    # The whole point: a catastrophic-looking delta must not be shown as if it
    # were a regression, because it is a different measurement.
    assert "hit_at_k" not in captured.out
    assert "REFUSING TO DIFF" in captured.err


def test_regression_beyond_tolerance_exits_one() -> None:
    rc = compare(
        baseline(prov(), hit_at_k=0.90),
        baseline(prov(), hit_at_k=0.80),
        tolerance=0.02,
    )
    assert rc == 1


def test_drop_within_tolerance_passes() -> None:
    rc = compare(
        baseline(prov(), hit_at_k=0.90),
        baseline(prov(), hit_at_k=0.89),
        tolerance=0.02,
    )
    assert rc == 0


def test_a_rise_in_false_abstention_is_a_regression() -> None:
    """The direction of "bad" is per-metric. false_abstention_rate going UP
    means the system answers fewer questions it can answer -- the user-facing
    failure -- so the same delta that is a win for hit@k is a loss here."""
    rc = compare(
        baseline(prov(), false_abstention_rate=0.10),
        baseline(prov(), false_abstention_rate=0.40),
        tolerance=0.02,
    )
    assert rc == 1


def test_a_fall_in_false_abstention_is_not_a_regression() -> None:
    rc = compare(
        baseline(prov(), false_abstention_rate=0.40),
        baseline(prov(), false_abstention_rate=0.10),
        tolerance=0.02,
    )
    assert rc == 0


def test_silencing_the_system_cannot_pass_as_an_improvement() -> None:
    """The exact shape of a bad score-floor change: correct_abstention_rate
    climbs to a perfect 1.0 while the system stops answering answerable
    questions. Gating on only the first number would call this a win."""
    rc = compare(
        baseline(prov(), correct_abstention_rate=0.60, false_abstention_rate=0.05,
                 hit_at_k=0.90),
        baseline(prov(), correct_abstention_rate=1.00, false_abstention_rate=0.68,
                 hit_at_k=0.32),
        tolerance=0.02,
    )
    assert rc == 1


def test_improvement_never_fails() -> None:
    rc = compare(
        baseline(prov(), hit_at_k=0.50),
        baseline(prov(), hit_at_k=0.95),
        tolerance=0.02,
    )
    assert rc == 0


def test_semantic_drift_still_reports_metrics_but_names_the_drift(capsys) -> None:
    rc = compare(
        baseline(prov(), hit_at_k=0.90),
        baseline(prov(retrieval_fetch_k=80), hit_at_k=0.92),
        tolerance=0.02,
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert "SEMANTIC DRIFT" in captured.out
    assert "retrieval_fetch_k" in captured.out


def test_tiers_are_never_averaged_together(capsys) -> None:
    old = {"provenance": prov(),
           "results": {"tier_a": {"hit_at_k": 0.90}, "tier_b": {"hit_at_k": 0.40}}}
    new = {"provenance": prov(),
           "results": {"tier_a": {"hit_at_k": 0.60}, "tier_b": {"hit_at_k": 0.90}}}
    rc = compare(old, new, tolerance=0.02)
    captured = capsys.readouterr()
    # tier_a regressed hard; a mean across tiers would have hidden it.
    assert rc == 1
    assert "[tier_a]" in captured.out and "[tier_b]" in captured.out


def test_fingerprint_ignores_soft_fields_and_tracks_hard_ones() -> None:
    assert fingerprint(prov()) == fingerprint(
        prov(git_sha="zzz", retrieval_fetch_k=80, llm_model="qwen2.5:3b")
    )
    assert fingerprint(prov()) != fingerprint(prov(chunk_size=512))


def test_field_classes_are_disjoint() -> None:
    for mode in (RETRIEVAL_MODE, FULL_MODE):
        hard, semantic, cosmetic = classify_fields(mode)
        assert len(set(hard) | set(semantic) | set(cosmetic)) == (
            len(hard) + len(semantic) + len(cosmetic)
        ), f"a field is classified twice in {mode} mode"


def test_a_metric_that_stops_being_reported_is_flagged(capsys) -> None:
    """A rename or a dropped field would otherwise pass as "no regression":
    the metric is simply absent from the new baseline and skipped in silence."""
    rc = compare(
        baseline(prov(), hit_at_k=0.90, false_abstention_rate=0.10),
        baseline(prov(), hit_at_k=0.90),
        tolerance=0.02,
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert "no longer gated: false_abstention_rate" in captured.out


def test_a_metric_absent_from_the_old_baseline_is_not_flagged(capsys) -> None:
    # The normal case for a newly added metric; nothing was lost.
    compare(
        baseline(prov(), hit_at_k=0.90),
        baseline(prov(), hit_at_k=0.90, false_abstention_rate=0.10),
        tolerance=0.02,
    )
    assert "no longer gated" not in capsys.readouterr().out


def test_the_admission_ceiling_is_cosmetic_not_silent() -> None:
    """4 -> 1 must be REPORTED and must not block the diff.

    It bounds concurrency, not what a query retrieves, so it is not semantic
    drift. But a field absent from the tuple entirely changes without comment,
    and this is the field that explains a latency difference between two runs.
    """
    verdict, hard, semantic, cosmetic = classify(
        prov(max_concurrent_queries=4), prov(max_concurrent_queries=1))
    assert verdict == COSMETIC
    assert [row[0] for row in cosmetic] == ["max_concurrent_queries"]
    assert not hard and not semantic


# --- R4: the two provenance gaps closed --------------------------------------

OCR_FIELDS = ["enable_ocr", "ocr_languages", "ocr_dpi"]
GENERATION_FIELDS = [
    "llm_num_ctx", "llm_temperature", "llm_num_predict", "llm_enable_thinking",
    "min_answer_chars", "rewrite_min_similarity", "strip_output_scaffolding",
    "strip_appended_decline", "strip_fabricated_headers",
    "strip_leading_citation_run",
]


@pytest.mark.parametrize("field,value", [
    ("enable_ocr", False), ("ocr_languages", "eng"), ("ocr_dpi", 400),
])
def test_OCR_SETTINGS_ARE_HARD_IN_BOTH_MODES(field, value) -> None:
    """OCR changes the TEXT EXTRACTED from scanned PDFs, therefore the stored
    vectors — exactly as chunk_size does, and chunk_size has always been hard.

    corpus_manifest_sha256 does not cover it: that hashes SOURCE files, not the
    text extracted from them. Two baselines across an ocr_dpi change used to
    compare COMPARABLE while measuring different corpora.
    """
    for mode in (RETRIEVAL_MODE, FULL_MODE):
        verdict, hard, _, _ = classify(
            prov(eval_mode=mode), prov(eval_mode=mode, **{field: value}))
        assert verdict == INCOMPARABLE, f"{field} must be hard in {mode} mode"
        assert [row[0] for row in hard] == [field]


@pytest.mark.parametrize("field", GENERATION_FIELDS)
def test_generation_flags_are_semantic_in_FULL_mode(field) -> None:
    """The generator is in the loop, so these move what is measured."""
    old = prov(eval_mode=FULL_MODE)
    new = prov(eval_mode=FULL_MODE, **{field: "CHANGED"})
    verdict, _, semantic, _ = classify(old, new)
    assert verdict == SEMANTIC
    assert [row[0] for row in semantic] == [field]


@pytest.mark.parametrize("field", GENERATION_FIELDS)
def test_generation_flags_are_cosmetic_in_RETRIEVAL_mode(field) -> None:
    """The LLM never runs, so they cannot have moved a single number — the same
    conditional treatment llm_model already had."""
    verdict, _, _, cosmetic = classify(prov(), prov(**{field: "CHANGED"}))
    assert verdict == COSMETIC
    assert [row[0] for row in cosmetic] == [field]


def test_require_support_quotes_is_HARD_in_full_mode() -> None:
    """Not merely semantic: MEASURED to collapse answering from 13/15 to 2/15.

    A run with it on and a run with it off are not one system being compared,
    they are two.
    """
    old = prov(eval_mode=FULL_MODE)
    new = prov(eval_mode=FULL_MODE, require_support_quotes=True)
    verdict, hard, _, _ = classify(old, new)
    assert verdict == INCOMPARABLE
    assert [row[0] for row in hard] == ["require_support_quotes"]


def test_require_support_quotes_is_cosmetic_in_retrieval_mode() -> None:
    verdict, _, _, cosmetic = classify(prov(), prov(require_support_quotes=True))
    assert verdict == COSMETIC


def test_llm_model_DIGEST_is_hard_in_full_mode() -> None:
    """`llama3.2:1b` is a moving tag, so the tag pins nothing.

    Recording only the tag let a full-mode baseline claim to describe a
    generator that upstream could republish underneath it — and every measured
    claim about abstention and grounding is a statement about one specific
    generator. Same reasoning that made `embed_model_digest` hard; it was simply
    never applied to the model on the other end.
    """
    old = prov(eval_mode=FULL_MODE, llm_model_digest="baf6a787")
    new = prov(eval_mode=FULL_MODE, llm_model_digest="0000ffff")
    verdict, hard, _, _ = classify(old, new)
    assert verdict == INCOMPARABLE
    assert [row[0] for row in hard] == ["llm_model_digest"]


def test_llm_model_digest_is_cosmetic_in_retrieval_mode() -> None:
    """Retrieval mode never calls the generator, so its identity cannot have
    moved a single number."""
    verdict, _, _, _ = classify(prov(), prov(llm_model_digest="anything-else"))
    assert verdict == COSMETIC


def test_retrieval_mode_records_NOT_APPLICABLE_rather_than_unpinned() -> None:
    """The two mean different things and must not collapse.

    "unpinned" = the generator ran and its identity was not captured, which
    makes a file a diagnostic rather than a reference. "not-applicable" = the
    generator never ran. Collapsing them would either downgrade every retrieval
    baseline to diagnostic, or hide a genuinely unpinned full-mode run.
    """
    from core.config import Settings
    from eval.provenance import build

    settings = Settings(_env_file=None, api_key="x")
    common = dict(corpus_manifest_sha256="abc", embed_model_digest="d",
                  n_answerable=1, n_unanswerable=1)

    retrieval = build(settings, eval_mode=RETRIEVAL_MODE, **common)
    assert retrieval["llm_model_digest"] == "not-applicable"

    full_unpinned = build(settings, eval_mode=FULL_MODE, **common)
    assert full_unpinned["llm_model_digest"] == "unpinned"

    full_pinned = build(settings, eval_mode=FULL_MODE,
                        llm_model_digest="baf6a787", **common)
    assert full_pinned["llm_model_digest"] == "baf6a787"


def test_every_recorded_field_is_classified_SOMEWHERE() -> None:
    """The gap-finding test.

    All three gaps closed so far — n_answerable, max_concurrent_queries and now
    the OCR and generation flags — were fields RECORDED in the tuple but absent
    from every class, so they changed silently. This makes that state
    impossible to reach again without failing a test.
    """
    from core.config import Settings
    from eval.provenance import build

    tuple_ = build(Settings(_env_file=None, api_key="x"),
                   corpus_manifest_sha256="abc", embed_model_digest="d",
                   eval_mode=RETRIEVAL_MODE, n_answerable=1, n_unanswerable=1)
    informational = {"recorded_at", "python"}
    for mode in (RETRIEVAL_MODE, FULL_MODE):
        hard, semantic, cosmetic = classify_fields(mode)
        classified = set(hard) | set(semantic) | set(cosmetic)
        unclassified = set(tuple_) - classified - informational
        assert not unclassified, (
            f"recorded but unclassified in {mode} mode: {sorted(unclassified)} — "
            f"these would change SILENTLY")
