from core.config import Settings
from models.schemas import RetrievedChunk
from services.retrieval import RetrievalService
from tests.unit.fakes import FakeEmbedder, FakeReranker, FakeVectorStore


def make_service(store: FakeVectorStore, **overrides) -> RetrievalService:
    settings = Settings(_env_file=None, **overrides)
    return RetrievalService(store, FakeEmbedder(), FakeReranker(), settings)


def make_chunk(seq, text, section="doc > Section A", source="a.docx", score=0.9):
    return RetrievedChunk(
        text=text,
        source=source,
        page_number=None,
        score=score,
        point_id=f"pid-{seq}",
        metadata={"chunk_seq": seq, "section_title": section, "source": source},
    )


def test_same_section_neighbor_prefix_is_stripped():
    store = FakeVectorStore()
    store.by_seq = {
        4: "doc > Section A\n\nprev text",   # same section: prefix stripped
        6: "doc > Section B\n\nnext text",   # different section: kept
    }
    service = make_service(store)

    chunk = make_chunk(5, "doc > Section A\n\ncore text")
    result = service._expand_with_neighbors([chunk])

    assert ("by_seq", "a.docx", [4, 6]) in store.calls
    assert result[0].text == (
        "prev text\n"                       # stripped duplicate prefix
        "doc > Section A\n\ncore text\n"    # core keeps its own prefix
        "doc > Section B\n\nnext text"      # cross-section path preserved
    )


def test_adjacent_winners_do_not_duplicate_neighbors():
    store = FakeVectorStore()
    store.by_seq = {s: f"text-{s}" for s in range(0, 10)}
    service = make_service(store)

    chunks = [make_chunk(5, "five"), make_chunk(6, "six")]
    service._expand_with_neighbors(chunks)

    # seq 5 claims 4 (6 is a winner already); seq 6 claims 7 (4 and 5 taken).
    fetches = [c for c in store.calls if c[0] == "by_seq"]
    assert fetches == [("by_seq", "a.docx", [4]), ("by_seq", "a.docx", [7])]


def test_chunks_without_seq_pass_through():
    store = FakeVectorStore()
    service = make_service(store)
    chunk = RetrievedChunk(text="t", source="s", page_number=None, score=0.5,
                           point_id="p", metadata={})
    assert service._expand_with_neighbors([chunk])[0].text == "t"
    assert store.calls == []
