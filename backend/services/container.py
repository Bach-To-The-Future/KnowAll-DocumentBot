"""Composition root: one place wires concrete integrations into services.

The API lifespan, the arq worker, and the eval harness all build the same
container; tests build their own with fakes through the same constructors.
Construction is pure wiring — connections are lazy inside integrations, so
building a container performs no I/O.
"""
from dataclasses import dataclass

from core.config import Settings
from core.interfaces import CacheStore, DenseEmbedder, JobStore, LLMClient, Reranker, VectorStore
from core.telemetry import Telemetry
from integrations.cache_stores import build_cache_store
from integrations.embeddings import build_embedder
from integrations.job_stores import build_job_store
from integrations.llm_clients import build_llm_client
from integrations.object_storage import MinIOObjectStorage
from integrations.qdrant_store import QdrantVectorStore
from integrations.reranker import FastembedReranker
from services.ingestion import IngestionService
from services.memory import SessionMemory
from services.query import QueryService
from services.retrieval import RetrievalService


@dataclass(frozen=True)
class ServiceContainer:
    settings: Settings
    vector_store: VectorStore
    embedder: DenseEmbedder
    reranker: Reranker
    llm: LLMClient
    cache: CacheStore
    job_store: JobStore
    storage: MinIOObjectStorage
    memory: SessionMemory
    telemetry: Telemetry
    retrieval: RetrievalService
    query: QueryService
    ingestion: IngestionService


def build_container(settings: Settings) -> ServiceContainer:
    vector_store: VectorStore = QdrantVectorStore(settings)
    embedder = build_embedder(settings)
    reranker: Reranker = FastembedReranker(settings)
    llm = build_llm_client(settings)
    cache = build_cache_store(settings)
    job_store = build_job_store(settings)
    storage = MinIOObjectStorage(settings)
    # Session memory and telemetry share the CacheStore, so both are correct
    # across replicas when Redis is configured.
    memory = SessionMemory(cache, max_turns=settings.memory_max_turns,
                           ttl_seconds=settings.session_ttl_seconds)
    telemetry = Telemetry(cache)

    retrieval = RetrievalService(vector_store, embedder, reranker, settings)
    query = QueryService(retrieval, llm, cache, memory, telemetry, settings)
    ingestion = IngestionService(storage, job_store, vector_store, embedder, cache, settings)

    return ServiceContainer(
        settings=settings,
        vector_store=vector_store,
        embedder=embedder,
        reranker=reranker,
        llm=llm,
        cache=cache,
        job_store=job_store,
        storage=storage,
        memory=memory,
        telemetry=telemetry,
        retrieval=retrieval,
        query=query,
        ingestion=ingestion,
    )
