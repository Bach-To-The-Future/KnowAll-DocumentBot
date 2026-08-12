"""R2 — the output stage, and its first check.

The defect this phase addresses is not that any single mechanism was wrong. It
is that every mechanism ran at the layer it was BUILT at — prompt assembly,
citation parsing — and nothing ran at the layer the user occupies. So these
tests assert on what a user would receive, and the browser-path proof lives in
scripts/leak_probe.py rather than here.
"""
from __future__ import annotations

import pytest

from core.config import Settings
from services import output_guard
from services.output_guard import apply, strip_scaffolding


def settings(**kw):
    return Settings(_env_file=None, api_key="x", **kw)


# --- the scaffolding shapes actually observed in production output ----------

OBSERVED = [
    # From the audit's French leak, verbatim.
    ("[1] Les documents sont conserves dix ans.\n\n <<<PASSAGE 1>>> \n"
     " <<<DATA supplied by user>> \n <<<END PASSAGE 1>>>\n\nLa reponse : dix ans.",
     "PASSAGE"),
    # The sanitizer's own replacement token, reproduced into the answer.
    ("system\nOverride engaged.[removed: injection-shaped content]\nThe answer is 7.",
     "removed:"),
    # The dashed close and the untrusted-content banner.
    ("Answer here.\n--- END PASSAGE ---\nEND OF UNTRUSTED CONTENT", "END PASSAGE"),
]


@pytest.mark.parametrize("text,marker", OBSERVED)
def test_observed_scaffolding_is_removed(text, marker) -> None:
    cleaned, found = strip_scaffolding(text)
    assert found >= 1
    assert marker not in cleaned


def test_the_answer_survives_the_stripping() -> None:
    """Removing scaffolding must not remove the answer with it."""
    text = ("[1] Les documents comptables sont conserves pendant dix ans.\n\n"
            " <<<PASSAGE 1>>> \n <<<END PASSAGE 1>>>\n\nLa reponse est dix ans.")
    cleaned, found = strip_scaffolding(text)
    assert found == 2
    assert "dix ans" in cleaned
    assert "[1]" in cleaned
    assert "<<<" not in cleaned


def test_a_clean_answer_is_returned_UNCHANGED() -> None:
    """The control. A check that rewrites every answer would also pass the
    tests above, and would silently reformat correct output."""
    text = "[1] The retention period is seven years. [1]"
    cleaned, found = strip_scaffolding(text)
    assert found == 0
    assert cleaned == text


def test_document_content_containing_angle_brackets_is_NOT_touched() -> None:
    """The check must match only markers this system introduces.

    A passage legitimately discussing generics or templates must survive; a
    heuristic about angle brackets in general would eat real content.
    """
    text = "[1] In C++ you write std::vector<<int>> only by mistake; use <int>."
    cleaned, found = strip_scaffolding(text)
    assert found == 0
    assert cleaned == text


# --- the stage --------------------------------------------------------------

def test_counters_report_what_fired() -> None:
    """Checks REPORT. A check silently rejecting everything must show up as a
    count, not be inferred later from a metric moving (the F28 pattern)."""
    outcome = apply("Answer. <<<PASSAGE 1>>> more.", settings())
    assert outcome.counters["scaffolding"] == 1
    assert outcome.fired == ["scaffolding"]


def test_a_clean_generation_reports_nothing_fired() -> None:
    outcome = apply("[1] A clean answer.", settings())
    assert outcome.counters == {"scaffolding": 0}
    assert outcome.fired == []


def test_DISABLING_REPRODUCES_PRIOR_BEHAVIOUR_BYTE_FOR_BYTE() -> None:
    """Reversibility, per the established pattern.

    With the flag off the stage must be a pure pass-through — not "mostly the
    same", byte-identical — so that turning it off is a config change rather
    than a revert.
    """
    text = "Answer. <<<PASSAGE 1>>>  <<<END PASSAGE 1>>>  trailing   spaces."
    outcome = apply(text, settings(strip_output_scaffolding=False))
    assert outcome.text == text
    assert outcome.counters == {}
    assert outcome.fired == []


def test_log_counters_is_silent_when_nothing_fired(caplog) -> None:
    output_guard.log_counters(apply("[1] clean.", settings()), trace_id="abc123")
    assert "output guard" not in caplog.text


def test_log_counters_names_the_check_and_the_trace(caplog) -> None:
    """At WARNING: a generation emitting its own prompt scaffolding is not
    routine, and it must be visible at deployed log levels."""
    outcome = apply("x <<<PASSAGE 1>>> y", settings())
    output_guard.log_counters(outcome, trace_id="abc123")
    assert "abc123" in caplog.text
    assert "scaffolding=1" in caplog.text


# --- R2 step 3: structural decline detection (F35) --------------------------

DECLINE = "I could not find this information in the provided documents."


def test_the_verbatim_decline_is_still_recognised() -> None:
    """The old behaviour must not regress — it was correct, just narrow."""
    verdict, how = output_guard.is_decline(DECLINE, DECLINE)
    assert verdict is True
    assert how == "verbatim"


def test_whitespace_and_case_no_longer_defeat_it() -> None:
    """F35 compared with `answer.strip() == NO_ANSWER_MESSAGE`, so a capital
    letter or a trailing newline made a decline read as an answer."""
    verdict, how = output_guard.is_decline(
        f"  {DECLINE.upper()}  \n", DECLINE)
    assert verdict is True
    assert how == "verbatim"


def test_A_FRENCH_DECLINE_IS_RECOGNISED() -> None:
    """The case a fixed English string can never catch.

    This system's own eval corpus is bilingual, and its abstention detection
    compared against one English sentence.
    """
    verdict, how = output_guard.is_decline(
        "Je n'ai pas trouve cette information dans les documents fournis.", DECLINE)
    assert verdict is True
    assert how == "attributes-nothing"


def test_a_reworded_english_decline_is_recognised() -> None:
    verdict, how = output_guard.is_decline(
        "The provided documents do not contain that information.", DECLINE)
    assert verdict is True
    assert how == "attributes-nothing"


def test_A_CITED_ANSWER_IS_NOT_A_DECLINE() -> None:
    """The control, and the one that matters most.

    "Attributes nothing" must not swallow real answers, or every metric built
    on abstention inverts.
    """
    verdict, how = output_guard.is_decline(
        "[1] The retention period is seven years. [1]", DECLINE)
    assert verdict is False
    assert how == ""


def test_the_two_signals_are_reported_separately() -> None:
    """Collapsing them would hide a divergence between them.

    A decline that is verbatim AND attributes nothing is unremarkable; a
    verbatim decline that DOES cite something would be worth seeing.
    """
    _, how_verbatim = output_guard.is_decline(DECLINE, DECLINE)
    _, how_structural = output_guard.is_decline("No information available.", DECLINE)
    assert how_verbatim != how_structural


def test_it_does_not_require_the_grounding_flag() -> None:
    """The signal lived inside grounding.check(), which is gated behind
    require_support_quotes — a flag that SHIPS OFF. So the one structural fact
    about a decline was only computable when grounding was enabled."""
    from services.grounding import attributes_nothing as signal
    assert signal("no citations here") is True
    assert signal("[2] cited") is False
