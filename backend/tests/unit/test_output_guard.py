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


ALL_CHECK_FLAGS = tuple(
    name for name in Settings.model_fields if name.startswith("strip_")
)


def test_a_clean_generation_reports_nothing_fired() -> None:
    """Every enabled check reports a zero, so "ran and found nothing" is
    distinguishable from "did not run" — the distinction that made the unwired
    stage invisible.

    Derives the check set rather than enumerating it: an earlier version listed
    the checks by name and broke on every legitimate addition, which is the
    brittleness pattern this engagement filed as P2-9.
    """
    outcome = apply("[1] A clean answer.", settings())
    # At least one check per flag; some flags gate more than one check
    # (strip_fabricated_headers gates both the stripper and the page-mismatch
    # REPORTER, which are different questions about the same header).
    assert len(outcome.counters) >= len(ALL_CHECK_FLAGS)
    assert all(v == 0 for v in outcome.counters.values())
    assert outcome.fired == []


def test_DISABLING_REPRODUCES_PRIOR_BEHAVIOUR_BYTE_FOR_BYTE() -> None:
    """Reversibility, per the established pattern.

    With the flag off the stage must be a pure pass-through — not "mostly the
    same", byte-identical — so that turning it off is a config change rather
    than a revert.
    """
    text = "[1] [2][3] Answer. <<<PASSAGE 1>>>  trailing   spaces. (Source: x.pdf)"
    outcome = apply(text, settings(**{flag: False for flag in ALL_CHECK_FLAGS}),
                    decline_message=DECLINE, citations=[])
    assert outcome.text == text
    assert outcome.counters == {}
    assert outcome.fired == []


def test_each_check_is_reversible_INDEPENDENTLY() -> None:
    """Disabling one check must not disable the other.

    Reversibility is per-check by design, so an operator can turn off the one
    that misbehaves without losing the rest.
    """
    text = "Answer. <<<PASSAGE 1>>>  trailing   spaces."
    baseline = len(apply(text, settings(), decline_message=DECLINE,
                         citations=[]).counters)
    for flag in ALL_CHECK_FLAGS:
        outcome = apply(text, settings(**{flag: False}),
                        decline_message=DECLINE, citations=[])
        assert len(outcome.counters) < baseline, (
            f"disabling {flag} must remove at least one check")
    # and a check still works while a DIFFERENT one is disabled
    outcome = apply(text, settings(strip_appended_decline=False),
                    decline_message=DECLINE, citations=[])
    assert "<<<" not in outcome.text


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


# --- R2 step 4: appended decline, and the wiring -----------------------------

def test_an_appended_decline_is_removed_from_a_cited_answer() -> None:
    text = f"[1] The retention period is seven years.\n\n{DECLINE}"
    cleaned, found = output_guard.strip_appended_decline(text, DECLINE)
    assert found == 1
    assert DECLINE not in cleaned
    assert "seven years" in cleaned


def test_a_MID_ANSWER_decline_is_removed_too() -> None:
    """Content-based, not positional.

    The observed case was trailing, but a decline sitting mid-answer is the
    same defect and a trailing-only check would pass it.
    """
    text = f"[1] Seven years.\n\n{DECLINE}\n\n[2] Approval is by the director."
    cleaned, found = output_guard.strip_appended_decline(text, DECLINE)
    assert found == 1
    assert DECLINE not in cleaned
    assert "Seven years" in cleaned and "director" in cleaned


def test_A_GENUINE_DECLINE_IS_LEFT_ALONE() -> None:
    """The path that must stay distinguishable.

    The generation IS the decline: it attributes nothing. Stripping it would
    leave an empty response — the defect D5 exists to prevent.
    """
    cleaned, found = output_guard.strip_appended_decline(DECLINE, DECLINE)
    assert found == 0
    assert cleaned == DECLINE


def test_a_decline_wearing_a_stray_citation_is_left_ALONE() -> None:
    """The belt-and-braces case the two signals alone do not cover.

    `[1]` makes it "attribute something", so the appendage branch is taken —
    but removing the sentence leaves only a citation marker, which is not an
    answer. The original is returned rather than an empty bubble.
    """
    text = f"[1] {DECLINE}"
    cleaned, found = output_guard.strip_appended_decline(text, DECLINE)
    assert found == 0
    assert cleaned == text


def test_appended_decline_is_reversible() -> None:
    text = f"[1] Seven years.\n\n{DECLINE}"
    outcome = apply(text, settings(strip_appended_decline=False),
                    decline_message=DECLINE)
    assert outcome.text == text


def test_THE_STAGE_IS_ACTUALLY_REACHED_FROM_THE_ANSWER_PATH() -> None:
    """The wiring, asserted separately from the checks.

    The stage was built, unit-tested and committed while `_guard_output` was
    DEFINED BUT NEVER CALLED. Every check passed in isolation; nothing ran in
    production; the browser probe showed no change. That is exactly the defect
    this phase exists to fix — asserting at the layer you built at rather than
    the layer the user occupies — reproduced inside its own fix.

    Source-level rather than behavioural because the alternative is a full
    QueryService with a fake LLM, and the thing that broke was one missing line.
    """
    import inspect

    from services.query import QueryService
    source = inspect.getsource(QueryService.answer_prepared)
    assert "_guard_output" in source, (
        "answer_prepared must call _guard_output; defining it is not enough."
    )


# --- R2 step 5: fabricated provenance headers, and the citation-only prefix --

RETRIEVED = [
    {"index": 1, "source": "cr-francais.pdf", "page_number": 1, "text": "..."},
    {"index": 2, "source": "System Design Concepts.docx", "page_number": 3, "text": "..."},
]


def test_A_HEADER_NAMING_AN_UNRETRIEVED_DOCUMENT_IS_STRIPPED() -> None:
    """The observed case, verbatim from the manual French sample: the answer
    cited `(Source: ABC DELF junior A2.pdf, Page: 114)` for a question about a
    retention policy, naming a document not in the retrieved set."""
    text = ("[1] Le plafond est de soixante mille euros. "
            "(Source: ABC DELF junior A2.pdf, Page: 114) et voila.")
    cleaned, found = output_guard.check_fabricated_headers(text, RETRIEVED)
    assert found == 1
    assert "ABC DELF" not in cleaned
    assert "soixante mille euros" in cleaned


def test_a_header_matching_a_retrieved_document_is_LEFT_ALONE() -> None:
    """build_prompt() renders this header above every passage, so a model
    copying it is being faithful, not fabricating."""
    text = "[1] Dix ans. (Source: cr-francais.pdf, Page: 1)"
    cleaned, found = output_guard.check_fabricated_headers(text, RETRIEVED)
    assert found == 0
    assert cleaned == text


def test_a_REAL_document_with_a_WRONG_PAGE_is_counted_not_stripped() -> None:
    """The ambiguous case, and the reason the check is asymmetric.

    The document is real and WAS in the context; the page may be a
    transcription slip or an invention. Stripping is destructive and
    irreversible from the user's side, so it is reserved for failures that
    cannot be anything else.
    """
    text = "[1] Dix ans. (Source: cr-francais.pdf, Page: 99)"
    cleaned, found = output_guard.check_fabricated_headers(text, RETRIEVED)
    assert found == 0, "a real source with a wrong page must not be stripped"
    assert cleaned == text


def test_no_citations_means_every_header_is_fabricated() -> None:
    text = "The answer is 7. (Source: invented.pdf, Page: 2)"
    cleaned, found = output_guard.check_fabricated_headers(text, [])
    assert found == 1
    assert "invented.pdf" not in cleaned


def test_a_clean_answer_is_untouched_by_the_header_check() -> None:
    text = "[1] The retention period is seven years."
    cleaned, found = output_guard.check_fabricated_headers(text, RETRIEVED)
    assert found == 0
    assert cleaned == text


# --- the citation-only prefix ------------------------------------------------

def test_the_citation_only_prefix_is_removed() -> None:
    """Observed: `[1] [2][3]\n\nI. Politique de conservation...`"""
    text = "[1] [2][3]\n\nI. Politique de conservation des documents."
    cleaned, found = output_guard.strip_leading_citation_run(text)
    assert found == 1
    assert cleaned.startswith("I. Politique")


def test_a_SINGLE_leading_citation_is_the_CORRECT_form_and_survives() -> None:
    """`[1] According to the policy...` is what the prompt asks for. Requiring
    two or more markers is what separates noise from the intended form."""
    text = "[1] According to the policy, seven years."
    cleaned, found = output_guard.strip_leading_citation_run(text)
    assert found == 0
    assert cleaned == text


def test_D5_ALONE_DOES_NOT_CATCH_THE_PREFIX() -> None:
    """Why this needs its own check.

    The malformed-generation guard rejects a generation whose SUBSTANTIVE
    content is empty, so it catches `[1] [1][3]` when that is the whole answer.
    With real prose after the markers, substance is large and D5 passes it —
    the noise reaches the user.
    """
    from services.query import substantive_text
    whole_answer = "[1] [1][3]"
    prefixed = "[1] [2][3]\n\nI. Politique de conservation des documents."
    assert substantive_text(whole_answer) == ""        # D5 rejects this
    assert len(substantive_text(prefixed)) > 20        # D5 passes this


def test_the_new_checks_are_reversible() -> None:
    text = "[1] [2][3]\n\nAnswer. (Source: invented.pdf, Page: 2)"
    outcome = apply(text, settings(strip_fabricated_headers=False,
                                   strip_leading_citation_run=False),
                    citations=RETRIEVED)
    assert "invented.pdf" in outcome.text
    assert outcome.text.startswith("[1] [2][3]")


# --- R2 step 6: streaming ----------------------------------------------------

def test_the_streaming_path_runs_the_stage_through_the_EXISTING_replace_event() -> None:
    """Wiring, asserted at source level for the same reason as the
    non-streaming one: what broke before was a single missing call.

    The stage must join D5's existing correction chain rather than introduce a
    second mechanism — one correction path is easier to reason about than two,
    and the client already handles `replace`.
    """
    import inspect

    from services.query import QueryService
    source = inspect.getsource(QueryService.stream_prepared)
    assert "_guard_output" in source, "stream_prepared must run the output stage"
    assert '"type": "replace"' in source, "corrections must use the existing event"
    # And it must not have grown a parallel correction event.
    assert source.count('"type": "replace"') == 1


def test_streaming_and_non_streaming_apply_the_SAME_checks() -> None:
    """A correction that only one path performs is a defect that only some
    users see — which is how the original three shipped."""
    import inspect

    from services.query import QueryService
    streaming = inspect.getsource(QueryService.stream_prepared)
    blocking = inspect.getsource(QueryService.answer_prepared)
    for call in ("_reject_if_malformed", "_check_grounding", "_guard_output"):
        assert call in streaming, f"{call} missing from the streaming path"
        assert call in blocking, f"{call} missing from the blocking path"


def test_a_page_mismatch_on_a_real_document_is_COUNTED() -> None:
    """The gap between what was documented and what was implemented.

    The header check was documented as counting this case and did not: it
    collected only never-retrieved sources, so a real document with an invented
    page was silently ignored. Documented behaviour the code does not perform is
    the defect this stage exists to fix, one level up.
    """
    text = "[1] Dix ans. (Source: cr-francais.pdf, Page: 99)"
    unchanged, count = output_guard.count_header_page_mismatches(text, RETRIEVED)
    assert count == 1
    assert unchanged == text, "this check reports; it must never rewrite"


def test_a_matching_page_is_not_counted() -> None:
    text = "[1] Dix ans. (Source: cr-francais.pdf, Page: 1)"
    _, count = output_guard.count_header_page_mismatches(text, RETRIEVED)
    assert count == 0


def test_a_fabricated_source_is_not_double_counted_as_a_page_mismatch() -> None:
    """The two counters must measure different things, or the second hides
    inside the first."""
    text = "[1] x. (Source: never-retrieved.pdf, Page: 4)"
    _, mismatches = output_guard.count_header_page_mismatches(text, RETRIEVED)
    _, fabricated = output_guard.check_fabricated_headers(text, RETRIEVED)
    assert mismatches == 0
    assert fabricated == 1


# --- the malformed-fence regression (final verification run) -----------------

MALFORMED = [
    # Observed VERBATIM in a French answer during end-to-end verification, with
    # the guard reporting scaffolding: 0 while all three reached the user.
    "<<<PASSAGE 1>> [1]  <<<PASSAGE 2>> [2][3]  <<<PASSAGE 3>> [3]",
    "<<<PASSAGE 1> and then the answer",
    "<<<END PASSAGE 2>> trailing text",
    "<<<DATA supplied by user>> more",
]


@pytest.mark.parametrize("text", MALFORMED)
def test_a_TRUNCATED_fence_is_still_stripped(text) -> None:
    """The model reproduces the fence imperfectly, so the closing run is
    tolerant. Requiring exactly `>>>` let two-bracket forms through."""
    cleaned, found = strip_scaffolding(text)
    assert found >= 1
    assert "<<<" not in cleaned


def test_the_exact_observed_leak_is_fully_removed() -> None:
    """Verbatim from the run, and nothing but citation markers should survive."""
    text = "<<<PASSAGE 1>> [1]  <<<PASSAGE 2>> [2][3]  <<<PASSAGE 3>> [3]"
    cleaned, found = strip_scaffolding(text)
    assert found == 3
    assert "PASSAGE" not in cleaned
    assert "[1]" in cleaned and "[3]" in cleaned


def test_two_opening_brackets_are_still_NOT_scaffolding() -> None:
    """The tolerance is on the CLOSING run only. `<<<` identifies scaffolding,
    so ordinary content with `<<` must survive — otherwise loosening the close
    would start eating document text."""
    for text in ("[1] In C++ you write std::vector<<int>> only by mistake.",
                 "[1] The shift operator a << b << c is not a fence.",
                 "[1] Compare a<<b and c>>d in one sentence."):
        cleaned, found = strip_scaffolding(text)
        assert found == 0, text
        assert cleaned == text
