"""Findings #19 and #3: the two budgets, and their opposite correct responses.

Neither boundary is reachable on the current corpus at current settings — max
stored chunk ~1056 against 2048, max assembled prompt 5375 against 8192. These
tests therefore guard a REGRESSION, which is the point: nothing else in the
system would notice a config change that made either reachable, and both
failure modes are silent.
"""
from __future__ import annotations

import pytest

from core.token_budget import (
    CONTEXT_TOKEN_LIMIT,
    EMBED_TOKEN_LIMIT,
    EmbeddingBudgetExceeded,
    check_embedding_budget,
    count_tokens,
    fit_context_budget,
)


def text_of(tokens: int) -> str:
    """Roughly `tokens` tokens of ordinary words."""
    return "retention policy record " * max(tokens // 3, 1)


# --- embedding: FAIL LOUD ----------------------------------------------------

def test_text_within_the_embedding_budget_passes() -> None:
    assert check_embedding_budget("records are retained", source="a.txt") > 0


def test_oversized_text_raises_rather_than_being_embedded() -> None:
    with pytest.raises(EmbeddingBudgetExceeded):
        check_embedding_budget(text_of(EMBED_TOKEN_LIMIT * 2), source="big.csv")


def test_the_error_explains_the_SILENT_failure_it_prevents() -> None:
    """A truncated embedding returns HTTP 200 with a well-formed vector. The
    message has to say that, or the next reader treats it as a size complaint."""
    with pytest.raises(EmbeddingBudgetExceeded) as exc:
        check_embedding_budget(text_of(EMBED_TOKEN_LIMIT * 2), source="big.csv")
    message = str(exc.value)
    assert "HTTP 200" in message and "WRONG vector" in message
    assert "big.csv" in message


def test_the_error_carries_the_measured_headroom_and_the_stacking_note() -> None:
    """A future violation is only interpretable with both: what the boundary
    used to be, and why nominal budgets understate real chunk size ~2x."""
    with pytest.raises(EmbeddingBudgetExceeded) as exc:
        check_embedding_budget(text_of(EMBED_TOKEN_LIMIT * 2), source="big.csv")
    message = str(exc.value)
    assert "1056" in message                       # measured max stored
    assert "2991" in message and "550" in message  # the stacking relationship


# --- context: DEGRADE GRACEFULLY ---------------------------------------------

def test_everything_is_kept_when_it_fits() -> None:
    chunks = [text_of(100) for _ in range(5)]
    kept, total, dropped = fit_context_budget("sys", "q?", chunks)
    assert kept == chunks and dropped == 0 and total < CONTEXT_TOKEN_LIMIT


def test_the_LOWEST_RANKED_chunks_are_dropped_first() -> None:
    """Rank order matters: the runtime truncates from the FRONT, where the
    grounding rules live. Dropping the worst passages is the opposite trade
    and the correct one."""
    chunks = [f"CHUNK{i} " + text_of(3000) for i in range(5)]
    kept, _, dropped = fit_context_budget("sys", "q?", chunks)
    assert dropped > 0
    assert kept[0].startswith("CHUNK0")
    assert all(f"CHUNK{i}" in "".join(kept) for i in range(len(kept)))
    # the tail is what went
    assert "CHUNK4" not in "".join(kept)


def test_at_least_one_chunk_survives_even_when_it_alone_exceeds_the_budget() -> None:
    """Answering from the best passage beats abstaining because the budget was
    tight — and an empty context would trigger the abstention path for a
    reason unrelated to the question."""
    kept, _, dropped = fit_context_budget(
        "sys", "q?", [text_of(CONTEXT_TOKEN_LIMIT * 2)])
    assert len(kept) == 1 and dropped == 0


def test_the_system_prompt_and_question_count_against_the_budget() -> None:
    """They are part of the assembled prompt; ignoring them is how a budget
    check passes while the real prompt overflows."""
    # Sized so BOTH fit — otherwise the cap truncates both to ~limit and the
    # comparison measures the cap rather than the overhead.
    chunks = [text_of(100) for _ in range(3)]
    _, small, dropped_small = fit_context_budget("sys", "q?", chunks)
    _, large, dropped_large = fit_context_budget(text_of(1500), text_of(500), chunks)
    assert dropped_small == 0 and dropped_large == 0
    assert large > small + 1500


def test_counting_is_monotone_in_length() -> None:
    assert count_tokens("a b c d e f") > count_tokens("a b")


# --- wired into the real paths, not just available ---------------------------

def test_build_prompt_enforces_the_context_budget() -> None:
    """The utility is worthless unenforced. This asserts the real assembly path
    calls it, by handing build_prompt more context than the budget allows."""
    from models.schemas import RetrievedChunk
    from services.query import QueryService

    chunks = [
        RetrievedChunk(text=f"CHUNK{i} " + text_of(3000), source=f"d{i}.txt",
                       page_number=None, score=1.0 - i / 100, point_id=str(i),
                       metadata={})
        for i in range(5)
    ]
    prompt = QueryService.build_prompt("How long are records retained?", chunks)
    assert "CHUNK0" in prompt, "the best-ranked passage must survive"
    assert "CHUNK4" not in prompt, "the worst-ranked passage must be dropped"


def test_ingestion_refuses_to_embed_an_oversized_chunk() -> None:
    """Finding #19 wired: the check runs before embed_documents, so a chunk
    that would be silently truncated fails the job instead."""
    from core.token_budget import EmbeddingBudgetExceeded

    class _Node:
        def __init__(self, text: str) -> None:
            self.text = text
            self.metadata: dict = {"source": "big.csv"}

    from services.ingestion import IngestionService
    ingestion = IngestionService.__new__(IngestionService)
    with pytest.raises(EmbeddingBudgetExceeded):
        ingestion._embed_chunks([_Node(text_of(EMBED_TOKEN_LIMIT * 2))])
