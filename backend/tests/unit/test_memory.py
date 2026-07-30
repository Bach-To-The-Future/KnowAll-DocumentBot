from services.memory import SessionMemory
from tests.unit.fakes import FakeCache


def make_memory(**kwargs) -> SessionMemory:
    return SessionMemory(FakeCache(), **kwargs)


def test_no_session_id_is_noop():
    memory = make_memory()
    memory.append_turn(None, "q", "a")
    assert memory.get_history(None) == []


def test_turns_capped_at_max():
    memory = make_memory(max_turns=5)
    for i in range(8):
        memory.append_turn("s1", f"q{i}", f"a{i}")
    history = memory.get_history("s1")
    assert len(history) == 5
    # Oldest turns dropped, newest kept, order preserved.
    assert history[0]["question"] == "q3"
    assert history[-1]["question"] == "q7"


def test_sessions_are_isolated():
    memory = make_memory()
    memory.append_turn("a", "qa", "aa")
    memory.append_turn("b", "qb", "ab")
    assert [t["question"] for t in memory.get_history("a")] == ["qa"]
    assert [t["question"] for t in memory.get_history("b")] == ["qb"]


def test_clear_session():
    memory = make_memory()
    memory.append_turn("s1", "q", "a")
    memory.clear_session("s1")
    assert memory.get_history("s1") == []


def test_corrupt_payload_degrades_to_empty():
    cache = FakeCache()
    memory = SessionMemory(cache)
    cache.set(SessionMemory._key("s1"), "{not json", 60)
    assert memory.get_history("s1") == []  # must not raise


def test_history_is_not_shared_state():
    memory = make_memory()
    memory.append_turn("s1", "q", "a")
    memory.get_history("s1").append({"question": "x", "answer": "y"})
    assert len(memory.get_history("s1")) == 1
