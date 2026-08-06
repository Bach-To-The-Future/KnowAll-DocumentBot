"""Abstract interfaces for the system's swappable components.

Services depend ONLY on these; integrations implement them. Tests inject
fakes through the same seams (see tests/unit/fakes.py).
"""
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol, runtime_checkable

from models.schemas import ScoredChunk, VectorRecord


@runtime_checkable
class ChunkLike(Protocol):
    """Anything extractors emit. Kept as a Protocol so core does not import
    llama_index (whose Document/TextNode satisfy it).

    Declared read-only: llama_index exposes `text` as a property, so a
    mutable-attribute Protocol did not match and every extractor's return type
    was reported incompatible. Consumers only READ `text` and MUTATE the dict
    returned by `metadata` (ingestion sets chunk_seq/etag on it) — they never
    rebind either attribute, so read-only is the accurate contract.
    """

    @property
    def text(self) -> str: ...

    @property
    def metadata(self) -> dict[str, Any]: ...


class DocumentExtractor(ABC):
    """Parses one file format into chunk objects ready for embedding."""

    @abstractmethod
    def extract_and_chunk(self, file_path: str) -> Sequence[ChunkLike]:
        """Raises ExtractionError when a readable file yields no content."""


class DenseEmbedder(ABC):
    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Aligned 1:1 with `texts`; raises EmbeddingError on any mismatch."""

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Query-task embedding (may apply model-specific prefixes + caching)."""


class Warmable:
    """Mixin (deliberately not an ABC — it has no abstract members).

    Component that can pre-load heavyweight state (ONNX models) before
    serving traffic. Declared on the interface so the lifespan warm-up is a
    typed contract rather than an `Any` attribute lookup on app.state."""

    def warm(self) -> None:
        """Load lazily-initialised resources. No-op by default; safe to call
        repeatedly and safe to call when nothing needs warming."""
        return None


class Reranker(Warmable, ABC):
    @abstractmethod
    def scores(self, query: str, texts: list[str]) -> list[float]:
        """Relevance in [0, 1], aligned 1:1 with `texts`."""


class VectorStore(Warmable, ABC):
    """Hybrid (dense + sparse) vector index. The sparse leg is an
    implementation detail of the store — callers pass raw query text."""

    @abstractmethod
    def ensure_ready(self) -> None:
        """Create collection/indexes; raise SchemaMigrationError on legacy schema."""

    @abstractmethod
    def missing_payload_indexes(self) -> list[str]:
        """Required payload indexes absent from the LIVE collection.

        On the interface because readiness depends on it (phase 2.6): a missing
        index makes filtered retrieval full-scan, which degrades silently as
        the collection grows and which no other signal in the system reports.
        Read back from the collection, never inferred from whether creation
        raised — a collection can be recreated after a successful create.
        """

    @abstractmethod
    def upsert(self, records: Sequence[VectorRecord]) -> None: ...

    @abstractmethod
    def hybrid_search(self, dense_vector: list[float], query_text: str,
                      k: int, filter_sources: list[str] | None = None) -> list[ScoredChunk]: ...

    @abstractmethod
    def fetch_chunks_by_seq(self, source: str, seqs: list[int]) -> dict[int, str]: ...

    @abstractmethod
    def fetch_section_chunks(self, source: str, section_title: str) -> dict[int, str]: ...

    @abstractmethod
    def delete_by_source(self, source: str) -> None: ...

    @abstractmethod
    def delete_stale(self, source: str, current_etag: str) -> None: ...

    @abstractmethod
    def reset(self) -> None: ...


class LLMClient(ABC):
    """Sync `complete` serves the short prompts issued inside prepare()
    (rewriting, expansion) — already running in a worker thread. The async
    methods carry the main generation path, so a 40-second answer never pins
    an anyio threadpool worker."""

    @abstractmethod
    def complete(self, prompt: str, system_prompt: str | None = None) -> str:
        """Raises GenerationError on failure — never returns an error string."""

    @abstractmethod
    async def acomplete(self, prompt: str, system_prompt: str | None = None) -> str:
        """Async, non-streaming completion."""

    @abstractmethod
    def astream(self, prompt: str, system_prompt: str | None = None) -> AsyncIterator[str]:
        """Async token stream; raises GenerationError on failure."""

    @abstractmethod
    async def aclose(self) -> None:
        """Release pooled connections (called from the app lifespan)."""


class CacheStore(ABC):
    """Best-effort KV cache: implementations log-and-degrade rather than
    raise, because a cache outage must never fail a request.

    The list and window operations exist so distributed state (telemetry
    ring buffer, fixed-window rate limiting) can live in Redis without
    services importing a Redis client directly.
    """

    @abstractmethod
    def get(self, key: str) -> str | None: ...

    @abstractmethod
    def set(self, key: str, value: str, ttl_seconds: int) -> None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def incr(self, key: str) -> int: ...

    @abstractmethod
    def incr_window(self, key: str, ttl_seconds: int) -> int:
        """INCR + set TTL on first write — the fixed-window rate limit
        primitive. Returns the post-increment counter."""

    @abstractmethod
    def list_push_trim(self, key: str, value: str, max_len: int, ttl_seconds: int) -> None:
        """LPUSH + LTRIM: a bounded ring buffer shared across replicas."""

    @abstractmethod
    def list_range(self, key: str, count: int) -> list[str]:
        """Newest-first slice of the ring buffer."""


class JobStore(ABC):
    @abstractmethod
    def update(self, job_id: str, **fields: Any) -> None: ...

    @abstractmethod
    def get(self, job_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def list_jobs(self, limit: int = 1000) -> list[dict[str, Any]]:
        """All tracked jobs. Used by the worker's startup sweep to find jobs
        left in a non-terminal state by a SIGKILL."""
