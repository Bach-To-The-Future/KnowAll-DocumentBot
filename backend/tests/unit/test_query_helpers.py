import pytest

from core.config import Settings
from core.exceptions import InvalidRequestError
from core.telemetry import Telemetry
from models.schemas import RetrievedChunk
from services.ingestion import sanitize_object_name
from services.memory import SessionMemory
from services.query import QueryService
from tests.unit.fakes import FakeCache, FakeEmbedder, FakeLLM, ScriptedEmbedder


def make_service(llm: FakeLLM, embedder=None, **overrides) -> QueryService:
    settings = Settings(_env_file=None, **overrides)
    cache = FakeCache()
    # Retrieval isn't exercised by these helper tests.
    return QueryService(retrieval=None, llm=llm, cache=cache,  # type: ignore[arg-type]
                        memory=SessionMemory(cache), telemetry=Telemetry(cache),
                        settings=settings, embedder=embedder or FakeEmbedder())


HISTORY = [{"question": "x", "answer": "y"}]


# --- needs_rewrite -----------------------------------------------------------

def test_no_history_never_rewrites():
    assert QueryService.needs_rewrite("How do I configure it?", []) is False


def test_short_followup_rewrites():
    assert QueryService.needs_rewrite("And the second one?", HISTORY) is True


def test_anaphora_rewrites():
    assert QueryService.needs_rewrite(
        "How exactly do I configure it in production environments?", HISTORY
    ) is True


def test_standalone_question_skips_rewrite():
    assert QueryService.needs_rewrite(
        "What are the stages of a data pipeline architecture?", HISTORY
    ) is False


# --- expand_queries parsing ---------------------------------------------------

def test_expansion_strips_numbering_and_dedupes():
    service = make_service(FakeLLM(response="1. Foo bar\n- Baz qux\nFoo bar\n\n"))
    variations = service.expand_queries("original question")
    assert variations == ["Foo bar", "Baz qux"][: Settings(_env_file=None).query_expansion_count]


def test_expansion_failure_returns_empty():
    service = make_service(FakeLLM(error=RuntimeError("llm down")))
    assert service.expand_queries("question") == []


# --- build_prompt -------------------------------------------------------------

def test_prompt_carries_provenance_tags():
    chunk = RetrievedChunk(text="chunk body", source="a.pdf", page_number=3,
                           score=0.9, point_id="p1", metadata={})
    prompt = QueryService.build_prompt("why?", [chunk])
    assert "[1] (Source: a.pdf, Page: 3)" in prompt
    assert prompt.rstrip().endswith("why?")


# --- sanitize_object_name --------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("../../etc/passwd", "passwd"),
    ("pdf/x.pdf", "x.pdf"),
    ("a\\b\\c.txt", "c.txt"),
    ("plain.docx", "plain.docx"),
])
def test_sanitize_collapses_paths(raw, expected):
    assert sanitize_object_name(raw) == expected


@pytest.mark.parametrize("bad", ["", "..", ".", "dir/", "a\x00b"])
def test_sanitize_rejects_invalid(bad):
    with pytest.raises(InvalidRequestError):
        sanitize_object_name(bad)


# --- finding #28: rewrite semantic-drift guard --------------------------------

ORIGINAL = "And the disposal rule?"
# The real rewrite observed in full-mode run 2026-08-04. Fluent, correctly
# sized, past every pre-existing guard, and about a different subject.
DRIFTED = "What is the policy on disposing of hazardous waste?"
FAITHFUL = "What is the records disposal rule?"

VECTORS = {
    ORIGINAL: [1.0, 0.0, 0.0],
    FAITHFUL: [0.95, 0.31, 0.0],   # cosine ~0.95
    DRIFTED: [0.30, 0.95, 0.0],    # cosine ~0.30
}


def drift_service(response: str, **overrides) -> QueryService:
    return make_service(FakeLLM(response=response),
                        embedder=ScriptedEmbedder(VECTORS), **overrides)


def test_a_fluent_correctly_sized_rewrite_about_the_wrong_subject_is_rejected():
    """The failure mode the old guards could not see. Length and non-emptiness
    say nothing about whether the subject survived."""
    result = drift_service(DRIFTED).rewrite(ORIGINAL, HISTORY)
    assert result.text == ORIGINAL          # fell back
    assert result.fired is False
    assert result.reason == "drift"
    assert result.rejected_text == DRIFTED  # kept for forensics
    assert result.similarity is not None and result.similarity < 0.55


def test_a_faithful_rewrite_is_kept():
    result = drift_service(FAITHFUL).rewrite(ORIGINAL, HISTORY)
    assert result.text == FAITHFUL
    assert result.fired is True
    assert result.reason == "ok"
    assert result.similarity is not None and result.similarity > 0.9


def test_the_drifted_rewrite_passes_every_pre_existing_guard():
    """Pins WHY finding #28 exists: the old code checked non-empty and length,
    and this rewrite satisfies both. Without the similarity guard it ships."""
    assert DRIFTED                                          # not empty
    assert len(DRIFTED) <= 4 * max(len(ORIGINAL), 80)       # not over-long
    # ...and it is still the wrong question.
    assert drift_service(DRIFTED, rewrite_min_similarity=0.0).rewrite(
        ORIGINAL, HISTORY).text == DRIFTED


def test_an_unmeasurable_similarity_never_rejects():
    """A broken embedder must degrade to the old behaviour, not start
    discarding every rewrite."""
    result = make_service(FakeLLM(response=DRIFTED),
                          embedder=FakeEmbedder()).rewrite(ORIGINAL, HISTORY)
    assert result.similarity is None
    assert result.text == DRIFTED
    assert result.fired is True


def test_rejection_is_distinguishable_from_never_attempted():
    """Both leave standalone == original. If the trace cannot tell them apart,
    a drift epidemic looks exactly like a quiet conversation."""
    rejected = drift_service(DRIFTED).rewrite(ORIGINAL, HISTORY)
    skipped = drift_service(DRIFTED).rewrite(ORIGINAL, [])
    assert rejected.text == skipped.text == ORIGINAL
    assert rejected.reason == "drift" and skipped.reason == "no-history"


def test_llm_failure_still_falls_back_without_consulting_the_embedder():
    def explode(*a, **k):
        raise AssertionError("embedder must not be called when the LLM failed")

    service = make_service(FakeLLM(error=RuntimeError("boom")),
                           embedder=ScriptedEmbedder(VECTORS))
    service._embedder.embed_query = explode  # type: ignore[method-assign]
    result = service.rewrite(ORIGINAL, HISTORY)
    assert result.text == ORIGINAL and result.reason == "llm-error"


def test_empty_and_overlong_rewrites_keep_their_own_reasons():
    assert drift_service("").rewrite(ORIGINAL, HISTORY).reason == "empty"
    assert drift_service("x" * 1000).rewrite(ORIGINAL, HISTORY).reason == "too-long"


# --- finding #32 / P-3 candidate D5: malformed-generation guard ---------------

# Verbatim outputs observed from llama3.2:1b on the near-miss probes.
OBSERVED_MALFORMED = ["[1] [1][3]", "[1] [2][3]"]


@pytest.mark.parametrize("raw", OBSERVED_MALFORMED)
def test_observed_citation_only_output_has_no_substantive_content(raw):
    from services.query import substantive_text
    assert substantive_text(raw) == ""


def test_a_real_answer_survives_citation_stripping():
    from services.query import substantive_text
    assert "records officer" in substantive_text(
        "According to [1], the records officer must authorise disposal."
    )


@pytest.mark.parametrize("raw", OBSERVED_MALFORMED)
def test_malformed_generation_becomes_the_abstention_message(raw):
    from services.query import NO_ANSWER_MESSAGE, PreparedQuery
    service = make_service(FakeLLM())
    prepared = PreparedQuery([], "", {}, None)
    assert service._reject_if_malformed(raw, prepared) == NO_ANSWER_MESSAGE
    # Recorded, not silently swallowed: the raw text is kept for forensics.
    assert prepared.trace["malformed_generation"] is True
    assert prepared.trace["malformed_raw"] == raw


def test_the_guard_passes_a_normal_answer_through():
    from services.query import PreparedQuery
    service = make_service(FakeLLM())
    answer = "According to [1], records are retained for seven years."
    prepared = PreparedQuery([], "", {}, None)
    assert service._reject_if_malformed(answer, prepared) == answer
    assert "malformed_generation" not in prepared.trace


def test_the_guard_never_rewrites_the_abstention_message():
    from services.query import NO_ANSWER_MESSAGE, PreparedQuery
    service = make_service(FakeLLM())
    prepared = PreparedQuery([], "", {}, None)
    assert service._reject_if_malformed(
        NO_ANSWER_MESSAGE, prepared) == NO_ANSWER_MESSAGE
    assert "malformed_generation" not in prepared.trace


def test_the_guard_is_reversible_at_zero():
    """P-3's standing requirement: a groundedness check that cannot be switched
    off is one nobody can measure the cost of. min_answer_chars=0 reproduces
    pre-2.4 behaviour exactly."""
    from services.query import PreparedQuery
    service = make_service(FakeLLM(), min_answer_chars=0)
    prepared = PreparedQuery([], "", {}, None)
    assert service._reject_if_malformed("[1] [1][3]", prepared) == "[1] [1][3]"
    assert "malformed_generation" not in prepared.trace
