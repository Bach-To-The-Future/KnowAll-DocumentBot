"""Dense embedding backends (Ollama batched /api/embed, OpenAI).

Both preserve strict input/output alignment — a silently dropped embedding
would misalign every subsequent text<->vector pair, so any shortfall raises
EmbeddingError. Query embeddings go through a small per-instance LRU.
"""
import logging
import threading
from collections import OrderedDict

import httpx
import openai

from core.config import Settings
from core.exceptions import EmbeddingError
from core.interfaces import DenseEmbedder

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 32
QUERY_CACHE_SIZE = 256

# nomic-embed-text was trained with task prefixes; embedding without them
# degrades retrieval. Applied to the embedding input only — stored payload
# text stays clean.
DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "


class _QueryCachingEmbedder(DenseEmbedder):
    """Shared LRU for single-query embeddings (repeated/expanded questions
    skip the backend round-trip; documents are embedded once, so caching
    them buys nothing)."""

    def __init__(self, model: str) -> None:
        self._model = model
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_lock = threading.Lock()

    def _embed_query_uncached(self, text: str) -> list[float]:
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:
        key = f"{self._model}:{text}"
        with self._cache_lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return list(self._cache[key])
        embedding = self._embed_query_uncached(text)
        with self._cache_lock:
            self._cache[key] = list(embedding)
            self._cache.move_to_end(key)
            while len(self._cache) > QUERY_CACHE_SIZE:
                self._cache.popitem(last=False)
        return embedding


class OllamaEmbedder(_QueryCachingEmbedder):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings.embed_model)
        self._embed_url = f"{settings.ollama_api_url}embed"  # batched endpoint
        # One HTTP stack for the whole service (llm_clients already uses
        # httpx). `requests` was imported here but never declared as a
        # dependency — it resolved only transitively via fastembed ->
        # huggingface_hub, so a change in that chain would have broken
        # embedding at runtime.
        self._client = httpx.Client(timeout=httpx.Timeout(connect=5.0, read=120.0,
                                                          write=30.0, pool=5.0))

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH_SIZE):
            batch = texts[start:start + EMBED_BATCH_SIZE]
            try:
                response = self._client.post(
                    self._embed_url,
                    json={"model": self._model, "input": batch},
                )
                response.raise_for_status()
            except httpx.HTTPError as e:
                raise EmbeddingError(
                    f"Ollama embedding request failed for batch starting at {start}",
                    detail=str(e),
                ) from e
            batch_embeddings = response.json().get("embeddings")
            if not isinstance(batch_embeddings, list) or len(batch_embeddings) != len(batch):
                raise EmbeddingError(
                    f"Ollama returned {len(batch_embeddings) if isinstance(batch_embeddings, list) else 0} "
                    f"embeddings for a batch of {len(batch)}; refusing misaligned results."
                )
            embeddings.extend(batch_embeddings)
        return embeddings

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._embed_batch([DOCUMENT_PREFIX + t for t in texts])

    def _embed_query_uncached(self, text: str) -> list[float]:
        return self._embed_batch([QUERY_PREFIX + text])[0]


class OpenAIEmbedder(_QueryCachingEmbedder):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings.embed_model)
        self._api_key = settings.openai_api_key

    def _embed(self, texts: list[str]) -> list[list[float]]:
        try:
            client = openai.OpenAI(api_key=self._api_key)
            response = client.embeddings.create(input=texts, model=self._model)
            return [d.embedding for d in response.data]
        except Exception as e:
            raise EmbeddingError("OpenAI embedding failed", detail=str(e)) from e

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        embeddings = self._embed(texts)
        if len(embeddings) != len(texts):
            raise EmbeddingError(
                f"OpenAI returned {len(embeddings)} embeddings for {len(texts)} texts."
            )
        return embeddings

    def _embed_query_uncached(self, text: str) -> list[float]:
        return self._embed([text])[0]


def build_embedder(settings: Settings) -> DenseEmbedder:
    if settings.use_openai_embedding:
        return OpenAIEmbedder(settings)
    return OllamaEmbedder(settings)
