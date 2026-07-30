from tests.unit.fakes import FakeVectorStore
from tests.unit.test_retriever_neighbors import make_chunk, make_service


def test_section_assembled_within_budget_and_prefix_stripped():
    section = "doc > Section A"
    store = FakeVectorStore()
    store.sections = {s: f"{section}\n\n" + f"body-{s} " * 5 for s in range(0, 7)}
    service = make_service(store)

    chunk = make_chunk(3, store.sections[3], section=section)
    result = service._expand_with_sections([chunk])[0]

    # Walks outward from seq 3; neighbors have the duplicate prefix stripped,
    # the core keeps its own.
    assert result.text.count(section) == 1
    assert "body-2" in result.text and "body-4" in result.text
    assert result.text.index("body-2") < result.text.index("body-3") < result.text.index("body-4")


def test_budget_limits_expansion():
    section = "doc > S"
    big = "x" * 3000
    store = FakeVectorStore()
    store.sections = {s: f"{section}\n\n{big}" for s in range(0, 5)}
    service = make_service(store)

    chunk = make_chunk(2, store.sections[2], section=section)
    result = service._expand_with_sections([chunk])[0]
    # Core ~3008 chars; budget 4000 leaves ~992 — no 3000-char neighbor fits.
    assert result.text == store.sections[2]


def test_seq_gap_stops_direction():
    section = "doc > S"
    store = FakeVectorStore()
    # seq 4 is missing: expansion upward must stop at the gap despite budget.
    store.sections = {2: "doc > S\n\ntwo", 3: "doc > S\n\nthree", 5: "doc > S\n\nfive"}
    service = make_service(store)

    chunk = make_chunk(3, store.sections[3], section=section)
    result = service._expand_with_sections([chunk])[0]
    assert "two" in result.text
    assert "five" not in result.text


def test_overlapping_winners_claim_once():
    section = "doc > S"
    store = FakeVectorStore()
    store.sections = {s: f"doc > S\n\nc{s}" for s in range(0, 6)}
    service = make_service(store)

    chunks = [make_chunk(2, store.sections[2], section=section),
              make_chunk(3, store.sections[3], section=section)]
    first, second = service._expand_with_sections(chunks)
    combined = first.text + "\n" + second.text
    # Every section chunk appears exactly once across both expanded winners.
    for s in range(0, 6):
        assert combined.count(f"c{s}") == 1, f"chunk {s} duplicated or missing"


def test_no_section_falls_back_to_window():
    store = FakeVectorStore()
    store.by_seq = {4: "prev", 6: "next"}
    service = make_service(store)

    chunk = make_chunk(5, "core", section=None)
    chunk.metadata.pop("section_title")
    result = service._expand_with_sections([chunk])[0]
    assert ("by_seq", "a.docx", [4, 6]) in store.calls
    assert all(c[0] != "section" for c in store.calls)
    assert result.text == "prev\ncore\nnext"
