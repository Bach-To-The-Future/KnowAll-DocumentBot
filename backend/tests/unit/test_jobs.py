from integrations.job_stores import InMemoryJobStore


def test_update_and_get_roundtrip():
    store = InMemoryJobStore()
    store.update("j1", status="queued", object_name="a.pdf")
    job = store.get("j1")
    assert job["status"] == "queued"
    assert job["object_name"] == "a.pdf"
    assert "updated_at" in job


def test_get_unknown_returns_none():
    assert InMemoryJobStore().get("nope") is None


def test_get_returns_copy():
    store = InMemoryJobStore()
    store.update("j1", status="queued")
    store.get("j1")["status"] = "tampered"
    assert store.get("j1")["status"] == "queued"


def test_eviction_only_removes_terminal_jobs():
    store = InMemoryJobStore(max_tracked=3)
    store.update("old-done", status="completed")
    store.update("running-1", status="running")
    store.update("running-2", status="running")
    store.update("new", status="queued")  # over cap -> evict "old-done" only
    assert store.get("old-done") is None
    assert store.get("running-1") is not None
    assert store.get("running-2") is not None
    assert store.get("new") is not None


def test_eviction_never_starves_when_all_live():
    store = InMemoryJobStore(max_tracked=2)
    store.update("r1", status="running")
    store.update("r2", status="running")
    store.update("r3", status="running")  # nothing terminal: cap exceeded, none dropped
    assert all(store.get(j) is not None for j in ("r1", "r2", "r3"))
