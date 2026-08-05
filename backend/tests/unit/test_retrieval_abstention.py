"""Proposal P-2 candidate C3: abstention and relevance are different questions.

Before C3, one number did both jobs. `rerank_score_floor = 0.25` was applied per
chunk, so a correctly-ranked FIRST-PLACE answer scoring 0.16 was discarded and
the user saw "I don't know" — and because a cross-encoder's absolute score
tracks chunk SHAPE (prose vs table vs OCR) as much as relevance, that fell
hardest on tables and scanned pages.

After C3:

    ABSTENTION  one very low bar on the BEST candidate. Below it, even the top
                hit is one the model confidently rejects.
    ORDERING    the reranker's job; rerank_top_n bounds the count. No per-chunk
                relevance judgement by default.

The tests below pin both halves, and specifically that C3 restores the
instrument: results are no longer collapsed to 0-or-1 items, which is what made
mrr_at_k identical to hit_at_k and left 60% of the golden set unable to move.
"""
from __future__ import annotations

from core.config import Settings
from models.schemas import ScoredChunk
from services.retrieval import RetrievalService
from tests.unit.fakes import FakeEmbedder, FakeReranker, FakeVectorStore


class ScriptedReranker(FakeReranker):
    def __init__(self, scores: list[float]) -> None:
        super().__init__()
        self._scores = scores

    def scores(self, query: str, texts: list[str]) -> list[float]:  # type: ignore[override]
        return self._scores[: len(texts)]


def candidate(name: str) -> ScoredChunk:
    return ScoredChunk(point_id=name, text=f"text of {name}", score=1.0,
                       payload={"source": f"{name}.txt"})


def service(scores: list[float], **overrides) -> RetrievalService:
    settings = Settings(_env_file=None, retrieval_context_mode="off", **overrides)
    return RetrievalService(FakeVectorStore(), FakeEmbedder(),
                            ScriptedReranker(scores), settings)


def pool(n: int) -> dict[str, ScoredChunk]:
    return {f"c{i}": candidate(f"c{i}") for i in range(n)}


# --- the defect C3 exists to fix ---------------------------------------------

def test_a_low_scoring_but_correctly_ranked_top_hit_is_no_longer_discarded() -> None:
    """The exact tier-B failure. 0.1602 was the correct answer for "How long
    must files be kept...", leading the runner-up by 57x, and the old 0.25
    floor threw it away."""
    chunks = service([0.1602, 0.0028, 0.0008])._rerank_pool("q", pool(3), k=5)
    assert chunks, "the top hit was discarded again"
    assert chunks[0].score == 0.1602


def test_the_old_behaviour_is_still_reachable_and_still_discards_it() -> None:
    """Pins that the regression is a config change, not a code change --
    rerank_score_floor is off by default, not deleted."""
    chunks = service([0.1602, 0.0028], rerank_score_floor=0.25)._rerank_pool(
        "q", pool(2), k=5)
    assert chunks == []


# --- abstention is now its own decision ---------------------------------------

def test_abstains_when_even_the_best_candidate_is_confidently_rejected() -> None:
    """abstention_score_floor is a "nothing coherent came back" bar, not a
    relevance judgement. 0.001 is a logit near -7: the model is certain."""
    assert service([0.001, 0.0005])._rerank_pool("q", pool(2), k=5) == []


def test_does_not_abstain_when_the_best_candidate_clears_the_bar() -> None:
    chunks = service([0.02, 0.001, 0.0005])._rerank_pool("q", pool(3), k=5)
    assert len(chunks) == 3


def test_abstention_looks_only_at_the_best_candidate() -> None:
    """Everything below rank 1 may be rubbish; that is an ordering problem, not
    an abstention one. If the top hit is coherent the query is answerable."""
    chunks = service([0.95, 0.0001, 0.0001])._rerank_pool("q", pool(3), k=5)
    assert len(chunks) == 3
    assert chunks[0].score == 0.95


def test_an_empty_candidate_pool_abstains_without_calling_the_reranker() -> None:
    assert service([])._rerank_pool("q", {}, k=5) == []


# --- C3 restores the instrument -----------------------------------------------

def test_results_are_no_longer_collapsed_to_a_single_item() -> None:
    """The sensitivity finding, as a test. Under the old floor these scores
    yielded ONE chunk, which made mrr_at_k identical to hit_at_k and left the
    metric unable to register any ordering change at all."""
    scores = [0.30, 0.20, 0.15, 0.10, 0.05]
    old = service(scores, rerank_score_floor=0.25)._rerank_pool("q", pool(5), k=5)
    new = service(scores)._rerank_pool("q", pool(5), k=5)
    assert len(old) == 1        # one item: no rank to reciprocate
    assert len(new) == 5        # mrr can now differ from hit@k


def test_rerank_top_n_bounds_the_count_not_the_floor() -> None:
    chunks = service([0.9, 0.8, 0.7, 0.6, 0.5, 0.4])._rerank_pool("q", pool(6), k=3)
    assert len(chunks) == 3
    assert [c.score for c in chunks] == [0.9, 0.8, 0.7]


def test_ordering_is_by_rerank_score_descending() -> None:
    chunks = service([0.2, 0.9, 0.5])._rerank_pool("q", pool(3), k=5)
    assert [c.score for c in chunks] == [0.9, 0.5, 0.2]
