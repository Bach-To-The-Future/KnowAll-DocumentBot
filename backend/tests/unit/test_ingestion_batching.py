"""Covers the Phase 3 streaming pipeline: bounded batches, global chunk_seq
numbering across batches, and the max-chunks guard."""
import sys
import types

import pytest

from core.config import Settings
from core.exceptions import ExtractionError
from services.ingestion import IngestionService
from tests.unit.fakes import FakeCache, FakeEmbedder, FakeVectorStore


class StubNode:
    def __init__(self, text: str) -> None:
        self.text = text
        self.metadata: dict = {}


class StubExtractor:
    def __init__(self, nodes) -> None:
        self._nodes = nodes

    def extract_and_chunk(self, file_path: str):
        return self._nodes


def make_service(store: FakeVectorStore, cache: FakeCache, **overrides) -> IngestionService:
    settings = Settings(_env_file=None, **overrides)
    return IngestionService(
        storage=None, job_store=None, vector_store=store,  # type: ignore[arg-type]
        embedder=FakeEmbedder(), cache=cache, settings=settings,
    )


def patch_extractor(monkeypatch, nodes) -> None:
    """Stub the registry module rather than importing it: these tests cover
    IngestionService alone and must not drag in every parser dependency."""
    stub = types.ModuleType("extraction.options")

    class ExtractStrategy:
        @classmethod
        def get_extractor(cls, file_path: str):
            return StubExtractor(nodes)

    stub.ExtractStrategy = ExtractStrategy  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "extraction.options", stub)


def test_upserts_in_bounded_batches(monkeypatch):
    nodes = [StubNode(f"chunk-{i}") for i in range(10)]
    patch_extractor(monkeypatch, nodes)
    store, cache = FakeVectorStore(), FakeCache()
    service = make_service(store, cache, ingest_batch_size=4)

    assert service.process_document("/tmp/doc.txt", etag="e1") == 10

    upserts = [c for c in store.calls if c[0] == "upsert"]
    # 10 chunks at batch size 4 -> 4 + 4 + 2, never one giant write.
    assert [len(c[1]) for c in upserts] == [4, 4, 2]


def test_chunk_seq_is_global_not_per_batch(monkeypatch):
    nodes = [StubNode(f"chunk-{i}") for i in range(7)]
    patch_extractor(monkeypatch, nodes)
    store, cache = FakeVectorStore(), FakeCache()
    make_service(store, cache, ingest_batch_size=3).process_document("/tmp/d.txt", etag="e1")

    # Batching must not renumber chunks: point IDs derive from chunk_seq, so
    # per-batch numbering would collide and silently overwrite.
    assert [n.metadata["chunk_seq"] for n in nodes] == list(range(7))
    assert {n.metadata["etag"] for n in nodes} == {"e1"}


def test_stale_delete_runs_once_after_all_batches(monkeypatch):
    patch_extractor(monkeypatch, [StubNode(f"c{i}") for i in range(5)])
    store, cache = FakeVectorStore(), FakeCache()
    make_service(store, cache, ingest_batch_size=2).process_document("/tmp/d.txt", etag="e2")

    kinds = [c[0] for c in store.calls]
    assert kinds.count("delete_stale") == 1
    assert kinds[-1] == "delete_stale"  # the atomic cut-over comes last


def test_over_limit_document_aborts_before_any_write(monkeypatch):
    patch_extractor(monkeypatch, [StubNode(f"c{i}") for i in range(11)])
    store, cache = FakeVectorStore(), FakeCache()
    service = make_service(store, cache, max_chunks_per_document=10)

    with pytest.raises(ExtractionError, match="over the limit"):
        service.process_document("/tmp/huge.csv", etag="e1")
    assert store.calls == []  # nothing partially indexed


def test_blank_only_document_is_rejected(monkeypatch):
    patch_extractor(monkeypatch, [StubNode("   "), StubNode("")])
    store, cache = FakeVectorStore(), FakeCache()
    with pytest.raises(ExtractionError):
        make_service(store, cache).process_document("/tmp/blank.txt", etag="e1")
