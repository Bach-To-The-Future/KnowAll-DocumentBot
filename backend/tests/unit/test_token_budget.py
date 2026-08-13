"""Findings #19 and #3: the two budgets, and their opposite correct responses.

The context boundary is not reachable on the current INDEXED corpus — max
assembled prompt 5375 against 8192 — so those tests guard a regression, which is
the point: nothing else would notice a config change that made it reachable, and
the failure mode is silent.

The embedding boundary IS reachable, and this docstring said otherwise for most
of the project's life. `b04-wide-row.csv` produces a single ~4,828-token chunk
against a 2,048-token window. It was authored to prove exactly that, then went
unnoticed because the eval collection was never rebuilt from scratch after the
guard landed — the claim "max stored chunk ~1056" described a corpus nobody had
re-ingested. See `test_the_oversized_row_fixture_still_reaches_the_boundary`.
"""
from __future__ import annotations

from pathlib import Path

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


# --- the boundary against a REAL file, not a synthetic one -------------------

WIDE_ROW_FIXTURE = (
    Path(__file__).resolve().parents[2] / "eval" / "corpus" / "tier-b" / "b04-wide-row.csv"
)


def test_the_oversized_row_fixture_still_reaches_the_boundary() -> None:
    """WHY THIS FILE EXISTS, AND WHY IT IS NOT INGESTED.

    `b04-wide-row.csv` was authored to prove finding #19's oversized-row path
    was REACHABLE — that a real extractor, on a real file, can hand the embedder
    a chunk larger than the model's window. The guard built for #19 then refused
    to ingest it, which is the correct outcome and also means the file can no
    longer live in the eval index: row-based chunking cannot split WITHIN a row,
    so there is no chunk size that makes this document embeddable. It carries
    `ingest: false` in eval/corpus/MANIFEST.yaml.

    Excluded from the index, kept as a fixture: this is the only artefact that
    demonstrates the boundary is reachable at all. Delete it and the guard's
    remaining tests all use `text_of(...)`, i.e. text this repository invented to
    be too long — which proves the check works, not that anything triggers it.

    Whether row-based chunking SHOULD split oversized rows is a live
    retrieval-quality question (docs/HANDOFF.md, open questions). This test must
    not be read as answering it. If that question is decided in favour of
    splitting, this test is what tells you the fixture is still doing its job.
    """
    from extraction.csv import ExtractCSV

    assert WIDE_ROW_FIXTURE.is_file(), (
        f"{WIDE_ROW_FIXTURE.name} is missing. It is not indexed, so nothing else "
        f"in the system will notice its absence — which is precisely why this "
        f"assertion exists."
    )

    chunks = ExtractCSV().extract_and_chunk(str(WIDE_ROW_FIXTURE))
    assert len(chunks) == 1, (
        f"expected ONE chunk (a single row that cannot be split), got {len(chunks)}. "
        f"If chunking changed, this fixture may no longer exercise the boundary."
    )

    tokens = count_tokens(chunks[0].text)
    assert tokens > EMBED_TOKEN_LIMIT, (
        f"the fixture no longer exceeds the embedding window "
        f"({tokens} <= {EMBED_TOKEN_LIMIT}); it has stopped proving what it exists to prove"
    )

    # And the guard refuses it — the reason it cannot be ingested.
    with pytest.raises(EmbeddingBudgetExceeded):
        check_embedding_budget(chunks[0].text, source=WIDE_ROW_FIXTURE.name)


def test_the_excluded_fixture_is_excluded_in_the_manifest_too() -> None:
    """The exclusion is a fact about the manifest, not a comment in a test.

    If someone flips `ingest: false` back without changing the chunker, corpus
    ingestion breaks again — and this fails first, next to the reason.
    """
    from eval.corpus import verify as corpus_verify

    assert WIDE_ROW_FIXTURE.name not in corpus_verify.ingested_documents(), (
        "b04-wide-row.csv is marked for ingestion, but it produces a single "
        "chunk over the embedding window and the token-budget guard will refuse "
        "it. Either revert the manifest change, or resolve the wide-table "
        "chunking question first (docs/HANDOFF.md)."
    )
