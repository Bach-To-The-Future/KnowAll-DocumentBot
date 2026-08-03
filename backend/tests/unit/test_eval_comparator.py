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
    ],
)
def test_hard_fields_refuse_comparison(field: str, value: object) -> None:
    verdict, hard, _, _ = classify(prov(), prov(**{field: value}))
    assert verdict == INCOMPARABLE
    assert [row[0] for row in hard] == [field]


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
