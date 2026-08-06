"""P-3 candidates D1+D6, landed as one mechanism: quote-backed grounding.

They were never really two candidates. D6 is D1 with the elicitation mode that
Control 3 proved works.

WHY THIS SHAPE, and not a model asking itself whether a claim is supported:
D3's control showed the 1B generator emits "NO" as a FIXED TOKEN under any
binary-verdict framing — it answered NO to "The sky is blue." against the
passage "The sky is blue.", and still answered NO when the labels were
inverted. But with no YES/NO framing it read the passage and answered
correctly. So the design uses only the mode that works:

    1. the generator quotes, open-ended, from the passage it cites
    2. the quote is checked to occur in that passage  <- PURE STRING MATCHING
    3. no quote, or a quote that is not there, means the claim has no textual
       basis in what was cited

No model judgement in step 2. No new runtime dependency. Nothing to calibrate.

WHAT THIS CATCHES
    fabricated citations — a quote that is not in the passage cannot be
    invented past a string comparison
    F32-class output — citation markers with no quote produce no support
    claims with no textual basis in the cited passage

WHAT THIS DOES NOT CATCH — a documented gap, not a solved problem:
    the benchmark inversion SURVIVES. Given "Les demandes doivent etre
    soumises avant le 31 mars", the model can quote that sentence perfectly
    and still assert that applications after 31 March receive the money. The
    quote is real; the reasoning from it is wrong. Only an entailment check
    (candidate D2) attacks that, and D2 remains OPEN.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# "[1] "quoted sentence"" — the tolerated shapes a 1B model actually produces.
_SUPPORT_LINE = re.compile(r'^\s*\[(\d+)\]\s*[:\-]?\s*"?(.+?)"?\s*$')
_SUPPORT_HEADER = re.compile(r"^\s*SUPPORT\s*:?\s*$", re.IGNORECASE)
_CITATION_RE = re.compile(r"\[\s*(\d+)\s*\]")


def normalize(text: str) -> str:
    """Collapse whitespace and casefold.

    A deliberate relaxation of "byte-for-byte": models re-wrap lines and
    re-capitalise the first word of a quote, and rejecting on that would
    measure formatting rather than grounding. It still requires the actual
    words in the actual order, which is the property the check depends on.
    """
    return " ".join(text.split()).casefold()


@dataclass
class GroundingResult:
    body: str                                  # the answer with SUPPORT stripped
    supported: bool
    reason: str                                # ok | no-quotes | quote-not-found | no-citations
    cited: list[int] = field(default_factory=list)
    quotes: dict[int, str] = field(default_factory=dict)
    unverified: list[tuple[int, str]] = field(default_factory=list)

    @property
    def emitted_quotes(self) -> bool:
        """Did the generator produce ANY quote at all?

        Reported separately from the match rate on purpose. A generator that
        stops quoting fails every claim and produces the refusal-machine
        outcome through a different door than a generator that quotes badly —
        and an aggregate number cannot tell them apart.
        """
        return bool(self.quotes)


def split_support(answer: str) -> tuple[str, dict[int, str]]:
    """Separate the visible answer from its SUPPORT block."""
    lines = answer.splitlines()
    header = next((i for i, ln in enumerate(lines) if _SUPPORT_HEADER.match(ln)), None)
    if header is None:
        return answer.strip(), {}

    quotes: dict[int, str] = {}
    for line in lines[header + 1:]:
        match = _SUPPORT_LINE.match(line)
        if match:
            index, quote = int(match.group(1)), match.group(2).strip()
            if quote:
                quotes.setdefault(index, quote)
    return "\n".join(lines[:header]).strip(), quotes


def rendered_block(citation: dict) -> str:
    """The passage AS THE MODEL SAW IT, provenance header included.

    build_prompt() renders each context block as

        [n] (Source: file.pdf, Page: 3)
        <chunk text>

    and the model, told to copy a sentence from passage n, sometimes copies
    that header along with the text — faithfully, because it is part of what
    was shown. Verifying only against `citation["text"]` then rejects a
    perfectly honest quote.

    MEASURED: this was D6's entire 1-in-15 failure. It is a harness defect, not
    a model one, and not a normalization artefact either — the quote was
    verbatim, against the wrong reference. Nondeterministic because the model
    includes the header only sometimes.

    Matching against BOTH forms keeps the check exact. No fuzzing, no
    similarity threshold, no semantic judgement.
    """
    page = citation.get("page_number")
    suffix = f", Page: {page}" if page is not None else ""
    header = f"(Source: {citation.get('source', '')}{suffix})"
    return f"{header}\n{citation.get('text', '')}"


def check(answer: str, citations: list[dict]) -> GroundingResult:
    """Verify every cited passage carries a quote that actually occurs in it."""
    body, quotes = split_support(answer)
    passages = {c["index"]: (normalize(c.get("text", "")),
                             normalize(rendered_block(c))) for c in citations}
    cited = sorted({int(n) for n in _CITATION_RE.findall(body)})

    if not cited:
        # No claim is attributed to anything. D5 handles the empty case; here
        # an unattributed assertion is simply not grounded.
        return GroundingResult(body, False, "no-citations", cited, quotes)
    if not quotes:
        return GroundingResult(body, False, "no-quotes", cited, quotes)

    unverified: list[tuple[int, str]] = []
    for index in cited:
        quote = quotes.get(index)
        if not quote:
            unverified.append((index, "<no quote supplied>"))
        elif not any(normalize(quote) in form
                     for form in passages.get(index, ("", ""))):
            unverified.append((index, quote))

    if unverified:
        return GroundingResult(body, False, "quote-not-found", cited, quotes, unverified)
    return GroundingResult(body, True, "ok", cited, quotes)
