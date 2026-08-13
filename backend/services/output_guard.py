"""Post-generation output handling — one stage, independent checks.

WHY THIS EXISTS

Three user-visible defects share one cause: **nothing inspected what the model
emitted before it reached the user.**

  P1-1  containment scaffolding reproduced into the answer — `<<<PASSAGE 1>>>`,
        `<<<END PASSAGE 1>>>`, and the sanitizer's own
        `[removed: injection-shaped content]`
  P1-2  the abstention string appended to a correct, cited answer
  P1-4  a provenance header fabricated into the visible text, naming a
        document unrelated to the question

Mechanisms already existed — the malformed-generation guard, citation-range
validation, the abstention check, the disabled grounding check — but they were
scattered and **none ran on final output**. That is the layer this stage adds,
and it is the layer the user occupies.

MEASURED BASELINE, through the browser, 9 queries per language, 376-point
production corpus with a French document ingested:

    lang    fence   trailing-abstention   fabricated-header
    fr      2/9     0/9                   1/9
    en      3/9     1/9                   1/9

NOTE ON LANGUAGE. The original audit measured 6/9 French and 0/9 English on a
4-document corpus and the defect looked French-specific. On the production
corpus it is not — English leaks slightly more. The real lesson is that these
are INTERMITTENT, so a single-language or small-n test undersamples them.

DESIGN RULES

1. Checks REPORT, they do not silently rewrite. Every check returns a counter,
   so a check that starts rejecting everything shows up as a count rather than
   being inferred later from a metric moving (the F28 pattern).
2. Each check is independently REVERSIBLE: a settings flag, a stated default,
   and a test pinning that disabling it reproduces prior behaviour byte-for-byte.
3. Checks run in a fixed order and each sees the previous one's output.

WHAT IS CHECKABLE MID-STREAM, AND WHAT IS NOT

Tokens cannot be un-sent, so the split is explicit:

  STREAMABLE   fence stripping, and any check that is a pure function of a
               bounded window of text. Scaffolding markers are short and
               self-delimiting, so they can be withheld until a boundary is
               resolved.
  COMPLETION   appended-decline removal (needs the whole answer to tell an
               appendage from the answer), fabricated provenance headers (needs
               the citation set), and anything comparing against the full
               citation array.

Completion-only checks reach the client through the `replace` event that D5
established, rather than a second mechanism. Streaming wiring is deliberately
the LAST step of this phase: the checks are proven on the non-streaming path
first, because a check that is wrong in a path where output cannot be recalled
is much more expensive than one that is wrong where it can.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from core.config import Settings
from services.grounding import attributes_nothing, split_support

logger = logging.getLogger(__name__)

# --- what the model must never emit -----------------------------------------

# The containment fences (services/passage_guard.py) and the sanitizer's own
# replacement token. These are OURS: they exist to structure the prompt, and
# their appearance in output is always a defect, never content.
# THE CLOSING DELIMITER IS DELIBERATELY TOLERANT, and that is the whole point.
#
# The model reproduces the fence IMPERFECTLY. The first version of this pattern
# required exactly `>>>`, having been written against the forms observed at the
# time. A later end-to-end run produced
#
#     <<<PASSAGE 1>> [1]  <<<PASSAGE 2>> [2][3]  <<<PASSAGE 3>> [3]
#
# — TWO closing brackets — and every one reached the user while the guard
# reported `scaffolding: 0`. It ran; it simply did not match.
#
# The earlier fix had handled `<<<DATA supplied by user>>` with `>?>?>?`, on
# that alternative alone: the specific malformed instance observed was patched
# instead of the class it belonged to. A garbled reproduction can truncate ANY
# of these forms, so the opening `<<<` is what identifies scaffolding and the
# closing run is allowed to be short.
#
# `<<<` (three) still identifies it, so document content like
# `std::vector<<int>>` — two opening brackets — is untouched. A test pins that.
_SCAFFOLDING = re.compile(
    r"<<<\s*/?\s*(?:END\s+)?PASSAGE[^>\n]{0,40}>{1,3}"   # <<<PASSAGE 1>>>, >>, >
    r"|<<<\s*DATA[^>\n]{0,80}>{0,3}"                     # <<<DATA supplied by user>>
    r"|<<<[^>\n]{0,80}>{1,3}"                            # any other triple-angle fence
    r"|\[removed:\s*injection-shaped content\]"          # the sanitizer's placeholder
    r"|-{2,}\s*END\s+PASSAGE\s*-{2,}"                    # the dashed form
    r"|END\s+OF\s+UNTRUSTED\s+CONTENT",
    re.IGNORECASE,
)

_CITATION_MARKER = re.compile(r"\[\s*\d+\s*\]")
_TRIM_CHARS = " \t\n\r.,;:—-[]()"


def is_decline(text: str, decline_message: str) -> tuple[bool, str]:
    """Is this generation a decline? Returns (verdict, how it was decided).

    R2 step 3 — F35's structural fix. Two independent signals:

      verbatim            the text IS the decline message, modulo whitespace
                          and case. Exact and cheap, but fails on any rewording
                          and cannot recognise a decline in another language.
      attributes-nothing  the text credits no passage. This is the STRUCTURAL
                          definition and it is language-independent: whatever
                          words it uses, an answer attributing nothing is not
                          an answer grounded in the corpus.

    F35 used only the first, as `answer.strip() == NO_ANSWER_MESSAGE`. That is a
    comparison against one fixed English sentence, in a system whose own eval
    corpus is bilingual.

    The two are reported separately rather than collapsed, so a divergence
    between them is visible instead of being silently resolved one way.
    """
    body, _ = split_support(text)
    if body.strip().casefold() == decline_message.strip().casefold():
        return True, "verbatim"
    if attributes_nothing(body):
        return True, "attributes-nothing"
    return False, ""


@dataclass
class GuardOutcome:
    """Result of running the stage. `counters` is the reportable part."""
    text: str
    counters: dict[str, int] = field(default_factory=dict)

    @property
    def fired(self) -> list[str]:
        return sorted(name for name, count in self.counters.items() if count)


# A check takes the current text and returns (new_text, n_findings).
Check = Callable[[str], tuple[str, int]]


def _substantive(text: str) -> str:
    """What is left once citation markers and punctuation are removed.

    Mirrors the malformed-generation guard's notion of substance: `[1] [1][3]`
    is not an answer.
    """
    return _CITATION_MARKER.sub("", text).strip(_TRIM_CHARS)


def _collapse(text: str) -> str:
    """Tidy the whitespace a removal leaves behind, without reflowing prose."""
    text = re.sub(r"\n{3,}", "\n\n", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def strip_scaffolding(text: str) -> tuple[str, int]:
    """P1-1. Remove containment scaffolding the model reproduced.

    DEFENCE IN DEPTH, NOT A FIX FOR THE CAUSE. A model echoing its own prompt
    scaffolding is a generator-capability symptom; a larger generator does not
    do it. This stops it reaching the user, which is worth doing regardless,
    but it does not make the generator follow instructions.

    Deliberately narrow: it matches only markers this system INTRODUCES. It must
    never touch document content, so there is no heuristic here about
    angle-brackets in general — a passage legitimately containing `<<<` survives
    unless it matches a scaffolding shape.
    """
    found = len(_SCAFFOLDING.findall(text))
    if not found:
        return text, 0
    return _collapse(_SCAFFOLDING.sub("", text)), found


def strip_appended_decline(text: str, decline_message: str) -> tuple[str, int]:
    """P1-2. Remove a decline sentence from a generation that also answers.

    CONTENT-BASED, NOT POSITIONAL. The observed case was a decline appended at
    the end, but a decline sentence sitting MID-ANSWER is the same defect and a
    trailing-only check would pass it — and this generator demonstrably produces
    structurally odd output under exactly these conditions (the manual French
    sample interleaved answers, headings and a fabricated provenance header).
    So the sentence is removed wherever it appears.

    THE TWO PATHS MUST STAY DISTINGUISHABLE, which is what is_decline's two
    signals are for:

      the generation IS a decline         attributes nothing -> LEAVE IT ALONE.
                                          It is the answer, and stripping would
                                          leave an empty response.
      a decline is APPENDED to an answer  attributes something -> strip the
                                          sentence, keep the cited answer.

    Using the verdict alone would collapse these and delete the answer in the
    first case. There is also a belt-and-braces check at the end: if removal
    leaves nothing substantive, the original is returned untouched, because an
    empty bubble is the defect D5 exists to prevent.
    """
    if not decline_message or decline_message not in text:
        return text, 0

    body, _ = split_support(text)
    # The whole generation is a decline: it credits no passage. Not an
    # appendage — the answer itself.
    if attributes_nothing(body):
        return text, 0

    cleaned = _collapse(text.replace(decline_message, ""))

    # Removal must never empty the response. If it would, the generation was
    # effectively a decline wearing a stray citation, and it stays as it was.
    if not _substantive(cleaned):
        return text, 0

    return cleaned, text.count(decline_message)


_HEADER = re.compile(r"\(\s*Source\s*:\s*([^,)]+?)\s*(?:,\s*Page\s*:\s*([^)]*?))?\s*\)",
                     re.IGNORECASE)
_LEADING_CITATIONS = re.compile(r"^\s*(?:\[\s*\d+\s*\]\s*){2,}")


def strip_leading_citation_run(text: str) -> tuple[str, int]:
    """Remove a run of bare citation markers opening an answer.

    Observed: `[1] [2][3]\\n\\nI. Politique de conservation...` — the answer
    begins with markers attached to nothing.

    NOT COVERED BY D5. The malformed-generation guard rejects a generation whose
    SUBSTANTIVE content is empty, so it catches `[1] [1][3]` when that is the
    WHOLE answer. Here the markers are a prefix on an otherwise substantial
    answer, so D5 passes it and the noise reaches the user.

    Deliberately requires TWO OR MORE adjacent markers. `[1] According to the
    policy...` is the normal, correct form and must survive; two or more markers
    with nothing between them attribute nothing to anything.
    """
    match = _LEADING_CITATIONS.match(text)
    if not match:
        return text, 0
    return text[match.end():].lstrip(), 1


def check_fabricated_headers(text: str, citations: list[dict]) -> tuple[str, int]:
    """P1-4. A provenance header in prose must match something retrieved.

    Mechanically checkable, with no model judgement: `(Source: X, Page: Y)`
    either corresponds to a chunk that was actually retrieved or it does not.

    THREE OUTCOMES, and only one of them strips:

      source retrieved, page agrees     legitimate. build_prompt() renders this
                                        header above every passage, so the model
                                        copying it is faithful, not fabrication.
                                        Left alone.
      source NEVER retrieved            unambiguous fabrication — the model
                                        invented a document. STRIPPED.
      source retrieved, page differs    AMBIGUOUS. The document is real and was
                                        in the context; the page may be a
                                        transcription slip or may be an
                                        invention. COUNTED, NOT STRIPPED.

    The asymmetry is deliberate. Stripping is destructive and irreversible from
    the user's side, so it is reserved for the case where the failure cannot be
    anything else. A wrong page number on a real document is still wrong, but it
    is reported rather than silently rewritten — and the counter makes it
    visible rather than leaving it to be inferred.
    """
    if not text:
        return text, 0

    known: dict[str, set[str]] = {}
    for citation in citations:
        source = str(citation.get("source", "")).strip().casefold()
        if not source:
            continue
        page = citation.get("page_number")
        known.setdefault(source, set()).add("" if page is None else str(page).strip())

    fabricated: list[str] = []
    for match in _HEADER.finditer(text):
        source = (match.group(1) or "").strip().casefold()
        if source not in known:
            fabricated.append(match.group(0))

    if not fabricated:
        return text, 0

    cleaned = text
    for header in fabricated:
        cleaned = cleaned.replace(header, "")
    return _collapse(cleaned), len(fabricated)


def count_header_page_mismatches(text: str, citations: list[dict]) -> tuple[str, int]:
    """Report headers naming a RETRIEVED document with a page that disagrees.

    REPORTS ONLY — the text is returned unchanged, always.

    This exists because the docstring above promised the ambiguous case would be
    "counted, not stripped", and the first implementation did neither: it
    collected only never-retrieved sources, so a real document with an invented
    page number was silently ignored. Documented behaviour that the code does not
    perform is the same defect this stage was built to fix, one level up.

    Kept as a separate check rather than folded into the header check, because
    "how many headers were fabricated" and "how many cited a real document with
    the wrong page" are different quantities and a single counter would hide the
    second inside the first.
    """
    if not text or not citations:
        return text, 0

    pages: dict[str, set[str]] = {}
    for citation in citations:
        source = str(citation.get("source", "")).strip().casefold()
        if not source:
            continue
        page = citation.get("page_number")
        pages.setdefault(source, set()).add("" if page is None else str(page).strip())

    mismatches = 0
    for match in _HEADER.finditer(text):
        source = (match.group(1) or "").strip().casefold()
        if source not in pages:
            continue  # fabricated; the other check owns it
        stated = (match.group(2) or "").strip()
        if stated and stated not in pages[source]:
            mismatches += 1
    return text, mismatches


def _enabled_checks(settings: Settings,
                    decline_message: str = "",
                    citations: list[dict] | None = None) -> list[tuple[str, Check]]:
    """Checks in run order, filtered by their reversibility flags."""
    checks: list[tuple[str, Check]] = []
    if settings.strip_output_scaffolding:
        checks.append(("scaffolding", strip_scaffolding))
    if settings.strip_appended_decline:
        # Closure: this check needs the decline message, which the Check
        # signature deliberately does not carry — every other check is a pure
        # function of the text.
        checks.append(("appended_decline",
                       lambda t: strip_appended_decline(t, decline_message)))
    if settings.strip_fabricated_headers:
        checks.append(("fabricated_header",
                       lambda t: check_fabricated_headers(t, citations or [])))
    if settings.strip_leading_citation_run:
        checks.append(("leading_citations", strip_leading_citation_run))
    if settings.strip_fabricated_headers:
        # Report-only, and gated by the same flag: it is the other half of the
        # same question about provenance headers.
        checks.append(("header_page_mismatch",
                       lambda t: count_header_page_mismatches(t, citations or [])))
    return checks


def apply(text: str, settings: Settings, *,
          decline_message: str = "",
          citations: list[dict] | None = None) -> GuardOutcome:
    """Run the stage over a completed generation.

    Returns the (possibly rewritten) text plus counters. Callers log the
    counters; this function does not decide policy.
    """
    counters: dict[str, int] = {}
    current = text
    for name, check in _enabled_checks(settings, decline_message, citations):
        current, found = check(current)
        counters[name] = found
    return GuardOutcome(current, counters)


def log_counters(outcome: GuardOutcome, *, trace_id: str) -> None:
    """One WARNING per generation that needed correcting, naming the checks.

    At WARNING because a generation that emits its own prompt scaffolding, or
    appends a decline to its own answer, is not routine — it is the signal that
    the generator is not following the output contract, and it should be visible
    at deployed log levels rather than only when someone goes looking (the same
    reason payload-index failures were moved off DEBUG in 2.6).
    """
    if not outcome.fired:
        return
    detail = ", ".join(f"{name}={outcome.counters[name]}" for name in outcome.fired)
    logger.warning(f"[trace {trace_id}] output guard corrected generation: {detail}")
