"""P-3 candidates D1+D6: quote-backed grounding.

The mechanism is deliberately dumb — string matching, no model judgement —
because D3's control proved the 1B generator cannot be steered into a verdict
token. These tests pin what it catches AND, just as importantly, the gap it
does not close.
"""
from __future__ import annotations

import pytest

from services import grounding

RETENTION = ("Retention Policy Notes. Records are retained for seven years "
             "from the date of creation. Disposal requires written "
             "authorisation from the records officer.")
AVIS = ("AVIS ARCHIVE. Le plafond de la subvention est de 75000 dollars. "
        "Les demandes doivent etre soumises avant le 31 mars.")


def cites(*passages: str) -> list[dict]:
    return [{"index": i, "text": t} for i, t in enumerate(passages, 1)]


# --- parsing -----------------------------------------------------------------

def test_support_block_is_split_off_the_visible_answer() -> None:
    body, quotes = grounding.split_support(
        'Records are kept seven years [1].\nSUPPORT:\n[1] "Records are retained '
        'for seven years from the date of creation."'
    )
    assert body == "Records are kept seven years [1]."
    assert quotes[1].startswith("Records are retained")


def test_an_answer_with_no_support_block_is_returned_whole() -> None:
    body, quotes = grounding.split_support("Just an answer [1].")
    assert body == "Just an answer [1]." and quotes == {}


@pytest.mark.parametrize("line", [
    '[1] "quoted"', "[1] quoted", "[1]: quoted", "[1] - quoted", "  [1]  quoted  ",
])
def test_tolerated_support_line_shapes(line: str) -> None:
    _, quotes = grounding.split_support(f"answer [1]\nSUPPORT:\n{line}")
    assert quotes == {1: "quoted"}


def test_whitespace_and_case_are_normalized_but_word_order_is_not() -> None:
    assert grounding.normalize("Records   are\nRETAINED") == "records are retained"
    assert grounding.normalize("retained are records") != grounding.normalize(
        "records are retained")


# --- what it catches ---------------------------------------------------------

def test_a_verbatim_quote_is_accepted() -> None:
    result = grounding.check(
        'Seven years [1].\nSUPPORT:\n[1] "Records are retained for seven years '
        'from the date of creation."', cites(RETENTION))
    assert result.supported and result.reason == "ok"
    assert result.body == "Seven years [1]."


def test_a_requoted_line_wrapped_by_the_model_is_still_accepted() -> None:
    """Rejecting on re-wrapping would measure formatting, not grounding."""
    result = grounding.check(
        "Seven years [1].\nSUPPORT:\n[1] Records   are retained\nfor seven years "
        "from the date of creation.", cites(RETENTION))
    assert result.supported


def test_a_fabricated_quote_is_rejected() -> None:
    result = grounding.check(
        'Exceptions are allowed [1].\nSUPPORT:\n[1] "The records officer may '
        'grant exceptions to the retention period."', cites(RETENTION))
    assert not result.supported and result.reason == "quote-not-found"
    assert result.unverified[0][0] == 1


def test_citation_only_output_produces_no_support() -> None:
    """F32's shape. D5 catches it first, but grounding must not pass it."""
    result = grounding.check("[1] [1][3]", cites(RETENTION, "x", "y"))
    assert not result.supported and result.reason == "no-quotes"


def test_a_cited_passage_with_no_quote_is_rejected() -> None:
    result = grounding.check(
        'Both things [1][2].\nSUPPORT:\n[1] "Records are retained for seven '
        'years from the date of creation."', cites(RETENTION, AVIS))
    assert not result.supported
    assert (2, "<no quote supplied>") in result.unverified


def test_a_quote_from_the_WRONG_passage_is_rejected() -> None:
    """The quote is real text, just not in the passage that was cited."""
    # Cites passage 1 (AVIS) but quotes a real sentence out of passage 2.
    result = grounding.check(
        'Seven years [1].\nSUPPORT:\n[1] "Records are retained for seven years '
        'from the date of creation."', cites(AVIS, RETENTION))
    assert not result.supported and result.reason == "quote-not-found"


def test_an_uncited_assertion_is_not_grounded() -> None:
    result = grounding.check("Records are kept for seven years.", cites(RETENTION))
    assert not result.supported and result.reason == "no-citations"


# --- the gap, pinned as a test so it cannot be quietly forgotten -------------

def test_THE_BENCHMARK_INVERSION_SURVIVES_THIS_CHECK() -> None:
    """DOCUMENTED GAP, not a solved problem.

    The model quotes the deadline sentence perfectly and still asserts that
    applications AFTER the deadline receive the money. The quote is real; the
    reasoning from it is wrong. Only an entailment check (candidate D2)
    attacks this, and D2 remains OPEN.

    If this test ever starts failing, something has closed the gap and the
    handoff needs updating.
    """
    result = grounding.check(
        'Le montant accorde aux demandes soumises apres le 31 mars est de 75000 '
        'dollars [1].\nSUPPORT:\n[1] "Les demandes doivent etre soumises avant '
        'le 31 mars."', cites(AVIS))
    assert result.supported, "the inversion is expected to pass D1+D6"


# --- emission rate vs match rate ---------------------------------------------

def test_no_quotes_and_bad_quotes_are_distinguishable() -> None:
    """The failure to watch is the generator declining to quote at all: every
    claim becomes unsupported and you get the refusal-machine outcome through a
    different door. An aggregate number cannot tell the two apart."""
    silent = grounding.check("Answer [1].\nSUPPORT:", cites(RETENTION))
    wrong = grounding.check(
        'Answer [1].\nSUPPORT:\n[1] "invented text"', cites(RETENTION))
    assert silent.emitted_quotes is False and silent.reason == "no-quotes"
    assert wrong.emitted_quotes is True and wrong.reason == "quote-not-found"
