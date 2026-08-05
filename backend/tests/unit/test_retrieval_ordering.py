"""Finding #30: context expansion runs AFTER the score floor.

`_rerank_pool` applies the floor at services/retrieval.py:182 and calls
`_expand_context` at :188. So the pipeline is

    fetch -> rerank -> FLOOR -> top-k -> expand

and enrichment can only ever reach chunks that already survived. A chunk
discarded for scoring 0.16 against a floor of 0.25 is discarded on the merits
of its bare text, and the section context that might have made it score higher
is fetched only for its luckier neighbours.

These tests PIN the current behaviour rather than assert the desired one. The
fix is not free: moving expansion before the floor means reranking expanded
text, which is proposal P-2 candidate C1 in everything but name -- so it is a
decision, not a cleanup. Until that decision lands, these tests make the
ordering explicit and will fail loudly if anyone changes it by accident.
"""
from __future__ import annotations

from core.config import Settings
from models.schemas import ScoredChunk
from services.retrieval import RetrievalService
from tests.unit.fakes import FakeEmbedder, FakeReranker, FakeVectorStore


class RecordingStore(FakeVectorStore):
    """Records which sections expansion asked for, so the test can prove that
    a discarded chunk's section was never fetched."""

    def __init__(self) -> None:
        super().__init__()
        self.section_requests: list[tuple[str, str]] = []
        self.seq_requests: list[tuple[str, list[int]]] = []

    def fetch_section_chunks(self, source: str, section: str) -> dict[int, str]:
        self.section_requests.append((source, section))
        # A sibling at seq+1 so expansion has something to attach; without one
        # the walk stops immediately and the test proves nothing.
        return {1: f"SECTION CONTEXT for {source}"}

    def fetch_chunks_by_seq(self, source: str, seqs: list[int]) -> dict[int, str]:
        self.seq_requests.append((source, list(seqs)))
        return {}


class ScriptedReranker(FakeReranker):
    """One score per candidate, in candidate order."""

    def __init__(self, scores: list[float]) -> None:
        super().__init__()
        self._scores = scores

    def scores(self, query: str, texts: list[str]) -> list[float]:  # type: ignore[override]
        return self._scores[: len(texts)]


def candidate(point_id: str, source: str, seq: int, text: str) -> ScoredChunk:
    return ScoredChunk(
        point_id=point_id,
        text=text,
        score=1.0,
        payload={"source": source, "chunk_seq": seq, "section_title": f"Sec {source}"},
    )


def service(store: RecordingStore, scores: list[float], **overrides) -> RetrievalService:
    settings = Settings(_env_file=None, retrieval_context_mode="section",
                        rerank_score_floor=0.25, **overrides)
    return RetrievalService(store, FakeEmbedder(), ScriptedReranker(scores), settings)


def test_a_chunk_cut_by_the_floor_never_has_its_section_fetched() -> None:
    """The defect, stated as a fact about the code. `below` is the correct
    answer in the tier-B failures; it is discarded on its bare text and its
    section is never even requested."""
    store = RecordingStore()
    pooled = {
        "above": candidate("above", "kept.txt", 0, "survives"),
        "below": candidate("below", "cut.txt", 0, "discarded"),
    }
    chunks = service(store, [0.90, 0.16])._rerank_pool("q", pooled, k=5)

    assert [c.source for c in chunks] == ["kept.txt"]
    fetched = {source for source, _ in store.section_requests}
    assert fetched == {"kept.txt"}
    assert "cut.txt" not in fetched, (
        "expansion reached a chunk the floor discarded — the ordering changed"
    )


def test_expansion_enriches_only_survivors() -> None:
    store = RecordingStore()
    pooled = {"a": candidate("a", "a.txt", 0, "alpha"),
              "b": candidate("b", "b.txt", 0, "beta")}
    chunks = service(store, [0.90, 0.80])._rerank_pool("q", pooled, k=5)
    # Both survived, so both got context. Nothing here is wrong; it is the
    # contrast case that makes the test above mean something.
    assert len(chunks) == 2
    assert all("SECTION CONTEXT" in c.text for c in chunks)


def test_the_floor_sees_bare_text_not_expanded_text() -> None:
    """A floor of 0.25 against a bare-text score of 0.16 is the tier-B failure
    shape. If expansion moved before the floor, the reranker would be scoring
    text containing 'SECTION CONTEXT' — this asserts it is not."""
    store = RecordingStore()
    seen: list[list[str]] = []

    class SpyReranker(ScriptedReranker):
        def scores(self, query: str, texts: list[str]) -> list[float]:
            seen.append(list(texts))
            return super().scores(query, texts)

    settings = Settings(_env_file=None, retrieval_context_mode="section",
                        rerank_score_floor=0.25)
    svc = RetrievalService(store, FakeEmbedder(), SpyReranker([0.90]), settings)
    svc._rerank_pool("q", {"a": candidate("a", "a.txt", 0, "alpha")}, k=5)

    assert seen == [["alpha"]]
    assert not any("SECTION CONTEXT" in t for t in seen[0])


def test_ordering_holds_in_window_mode_too() -> None:
    store = RecordingStore()
    settings = Settings(_env_file=None, retrieval_context_mode="window",
                        rerank_score_floor=0.25, neighbor_window=1)
    svc = RetrievalService(store, FakeEmbedder(), ScriptedReranker([0.90, 0.16]), settings)
    pooled = {"above": candidate("above", "kept.txt", 5, "survives"),
              "below": candidate("below", "cut.txt", 5, "discarded")}
    svc._rerank_pool("q", pooled, k=5)
    assert {source for source, _ in store.seq_requests} == {"kept.txt"}
