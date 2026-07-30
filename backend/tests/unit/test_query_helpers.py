import pytest

from core.config import Settings
from core.exceptions import InvalidRequestError
from core.telemetry import Telemetry
from models.schemas import RetrievedChunk
from services.ingestion import sanitize_object_name
from services.memory import SessionMemory
from services.query import QueryService
from tests.unit.fakes import FakeCache, FakeLLM


def make_service(llm: FakeLLM) -> QueryService:
    settings = Settings(_env_file=None)
    cache = FakeCache()
    # Retrieval isn't exercised by these helper tests.
    return QueryService(retrieval=None, llm=llm, cache=cache,  # type: ignore[arg-type]
                        memory=SessionMemory(cache), telemetry=Telemetry(cache),
                        settings=settings)


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
