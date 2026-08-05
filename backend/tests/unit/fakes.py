"""Interface fakes for unit tests — injected through the same constructor
seams production uses; no monkeypatching of module globals required."""
from collections.abc import AsyncIterator, Sequence

from core.interfaces import CacheStore, DenseEmbedder, LLMClient, Reranker, VectorStore
from models.schemas import ScoredChunk, VectorRecord


class FakeVectorStore(VectorStore):
    """No-op store; tests override the fetch methods they exercise."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.by_seq: dict[int, str] = {}
        self.sections: dict[int, str] = {}

    def ensure_ready(self) -> None:  # pragma: no cover - trivial
        pass

    def upsert(self, records: Sequence[VectorRecord]) -> None:
        self.calls.append(("upsert", [r.text for r in records]))

    def hybrid_search(self, dense_vector, query_text, k, filter_sources=None) -> list[ScoredChunk]:
        return []

    def fetch_chunks_by_seq(self, source: str, seqs: list[int]) -> dict[int, str]:
        self.calls.append(("by_seq", source, sorted(seqs)))
        return {s: self.by_seq[s] for s in seqs if s in self.by_seq}

    def fetch_section_chunks(self, source: str, section_title: str) -> dict[int, str]:
        self.calls.append(("section", source, section_title))
        return dict(self.sections)

    def delete_by_source(self, source: str) -> None:
        self.calls.append(("delete_by_source", source))

    def delete_stale(self, source: str, current_etag: str) -> None:
        self.calls.append(("delete_stale", source, current_etag))

    def reset(self) -> None:  # pragma: no cover - trivial
        pass


class FakeEmbedder(DenseEmbedder):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.0]


class FakeReranker(Reranker):
    def __init__(self, fixed: float = 0.9) -> None:
        self._fixed = fixed

    def scores(self, query: str, texts: list[str]) -> list[float]:
        return [self._fixed] * len(texts)


class FakeLLM(LLMClient):
    def __init__(self, response: str = "", error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.prompts: list[str] = []
        self.closed = False

    def complete(self, prompt: str, system_prompt: str | None = None) -> str:
        if self._error:
            raise self._error
        self.prompts.append(prompt)
        return self._response

    async def acomplete(self, prompt: str, system_prompt: str | None = None) -> str:
        return self.complete(prompt, system_prompt)

    async def astream(self, prompt: str, system_prompt: str | None = None) -> AsyncIterator[str]:
        if self._error:
            raise self._error
        yield self._response

    async def aclose(self) -> None:
        self.closed = True


class FakeCache(CacheStore):
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.counters: dict[str, int] = {}
        self.lists: dict[str, list[str]] = {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self.data[key] = value

    def delete(self, key: str) -> None:
        self.data.pop(key, None)

    def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    def incr_window(self, key: str, ttl_seconds: int) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    def list_push_trim(self, key: str, value: str, max_len: int, ttl_seconds: int) -> None:
        bucket = self.lists.setdefault(key, [])
        bucket.insert(0, value)
        del bucket[max_len:]

    def list_range(self, key: str, count: int) -> list[str]:
        return self.lists.get(key, [])[:count]


class ScriptedEmbedder(DenseEmbedder):
    """Maps exact strings to vectors so a test can dictate cosine similarity.

    Unknown text gets an orthogonal vector, so anything the test did not name
    is maximally dissimilar — a rewrite the test forgot to script reads as
    drift rather than silently passing the guard.
    """

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vectors.get(text, [0.0, 0.0, 1.0])
