"""Qdrant implementation of the VectorStore interface.

Owns everything Qdrant-specific: named dense+sparse vectors, RRF fusion,
int8 quantization, payload indexes, deterministic point IDs, and the BM25
sparse leg (fastembed) — callers pass raw query text and never see qdrant
or fastembed types.
"""
import logging
import threading
import uuid
from collections.abc import Sequence
from typing import Any

from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from core.config import Settings
from core.exceptions import SchemaMigrationError, VectorStoreError
from core.interfaces import VectorStore
from models.schemas import ScoredChunk, VectorRecord

logger = logging.getLogger(__name__)

# The hot filter paths. Absence means a full scan, not an error.
REQUIRED_PAYLOAD_INDEXES = (
    ("source", qm.PayloadSchemaType.KEYWORD),
    ("chunk_seq", qm.PayloadSchemaType.INTEGER),
    ("section_title", qm.PayloadSchemaType.KEYWORD),
    # Phase 4.3: `etag` is FILTERED by delete_stale() — the staged swap's
    # must_not clause — and was never indexed, so the atomic cut-over of every
    # ingest ran a full scan. Found by auditing which payload fields appear in
    # a FieldCondition rather than by profiling, because a full scan on a small
    # collection is invisible until it is not.
    ("etag", qm.PayloadSchemaType.KEYWORD),
)

DENSE_VECTOR = "dense"
SPARSE_VECTOR = "sparse"

# Fixed namespace so the same (source, etag, chunk_seq) always yields the same
# point ID: re-ingesting an unchanged file overwrites points in place instead
# of duplicating them.
POINT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "knowall-documentbot")


def make_point_id(source: str, etag: str, chunk_seq: int) -> str:
    """Deterministic point ID -> idempotent upserts."""
    return str(uuid.uuid5(POINT_NAMESPACE, f"{source}:{etag}:{chunk_seq}"))


class QdrantVectorStore(VectorStore):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._collection = settings.qdrant_collection
        self._client: QdrantClient | None = None
        self._client_lock = threading.Lock()
        self._sparse_model: SparseTextEmbedding | None = None
        # fastembed models are not documented thread-safe; BM25 encoding is
        # fast enough to serialize behind one lock.
        self._sparse_lock = threading.Lock()

    # --- connections (lazy: importing/constructing never does I/O) ---------

    def _get_client(self) -> QdrantClient:
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    try:
                        client = QdrantClient(
                            host=self._settings.qdrant_host,
                            port=self._settings.qdrant_port,
                            # Without an explicit timeout a hung Qdrant holds a
                            # request thread indefinitely (thread starvation).
                            timeout=self._settings.qdrant_timeout,
                            api_key=self._settings.qdrant_api_key,
                            # qdrant-client implicitly switches to HTTPS when an
                            # api_key is set; our Qdrant speaks plaintext on the
                            # internal network, so the handshake fails. Set
                            # QDRANT_HTTPS=true once TLS terminates in front of it.
                            https=self._settings.qdrant_https,
                        )
                        client.get_collections()
                    except Exception as e:
                        raise VectorStoreError(
                            f"Failed to connect to Qdrant at "
                            f"{self._settings.qdrant_host}:{self._settings.qdrant_port}",
                            detail=str(e),
                        ) from e
                    self._client = client
        return self._client

    def warm(self) -> None:
        """Warmable: pre-load the BM25 model so the first upsert/query does
        not pay the load cost inside a request."""
        self.get_sparse_model()

    def get_sparse_model(self) -> SparseTextEmbedding:
        if self._sparse_model is None:
            with self._sparse_lock:
                if self._sparse_model is None:
                    logger.info(f"Loading sparse embedding model: {self._settings.sparse_model}")
                    self._sparse_model = SparseTextEmbedding(model_name=self._settings.sparse_model)
        return self._sparse_model

    def _sparse_documents(self, texts: list[str]) -> list[qm.SparseVector]:
        model = self.get_sparse_model()
        with self._sparse_lock:
            return [
                qm.SparseVector(indices=e.indices.tolist(), values=e.values.tolist())
                for e in model.embed(texts)
            ]

    def _sparse_query(self, text: str) -> qm.SparseVector:
        # BM25 weights query terms differently from documents.
        model = self.get_sparse_model()
        with self._sparse_lock:
            # query_embed returns an Iterable, not an Iterator: iter() first.
            e = next(iter(model.query_embed(text)))
        return qm.SparseVector(indices=e.indices.tolist(), values=e.values.tolist())

    # --- schema -------------------------------------------------------------

    def _is_hybrid_schema(self, info: Any) -> bool:
        vectors = info.config.params.vectors
        sparse = info.config.params.sparse_vectors or {}
        return isinstance(vectors, dict) and DENSE_VECTOR in vectors and SPARSE_VECTOR in sparse

    def _ensure_payload_indexes(self) -> None:
        """Indexes for the hot filter paths: source (selection, deletion),
        chunk_seq (window expansion), section_title (parent retrieval).

        Phase 2.6: failures are WARNING, not debug. A missing payload index is
        not a cosmetic problem — Qdrant falls back to a full scan, so filtered
        retrieval silently gets slower as the collection grows and nothing
        surfaces until someone profiles it. DEBUG meant it never appeared in
        any deployed log level.
        """
        client = self._get_client()
        for field_name, schema in REQUIRED_PAYLOAD_INDEXES:
            try:
                client.create_payload_index(
                    collection_name=self._collection, field_name=field_name, field_schema=schema
                )
            except Exception as e:
                # "already exists" is the common, benign case and Qdrant reports
                # it as an error, so it is separated rather than shouted about.
                if "already exists" in str(e).lower():
                    logger.debug(f"[Qdrant] Payload index '{field_name}' already present.")
                else:
                    logger.warning(
                        f"[Qdrant] Payload index '{field_name}' could not be created: {e}. "
                        f"Filtered retrieval on this field will FULL SCAN, which "
                        f"degrades silently as the collection grows."
                    )

    def missing_payload_indexes(self) -> list[str]:
        """Which required indexes are absent. Empty list = healthy.

        Read back from the collection rather than inferred from whether
        creation raised: creation can succeed against a collection that is
        later recreated, and the only honest check is what is there now.
        """
        try:
            info = self._get_client().get_collection(self._collection)
        except Exception as e:
            logger.warning(f"[Qdrant] Could not read collection schema: {e}")
            return []  # unknown is not the same as missing; readiness owns liveness
        present = set((info.payload_schema or {}).keys())
        return [name for name, _ in REQUIRED_PAYLOAD_INDEXES if name not in present]

    def ensure_ready(self) -> None:
        client = self._get_client()
        existing = [c.name for c in client.get_collections().collections]
        if self._collection not in existing:
            logger.info(f"[Qdrant] Creating hybrid collection: {self._collection}")
            try:
                client.create_collection(
                    collection_name=self._collection,
                    vectors_config={
                        DENSE_VECTOR: qm.VectorParams(
                            size=self._settings.embed_dim, distance=qm.Distance.COSINE
                        )
                    },
                    sparse_vectors_config={
                        # IDF modifier is required for BM25-style sparse vectors.
                        SPARSE_VECTOR: qm.SparseVectorParams(modifier=qm.Modifier.IDF)
                    },
                    # int8 scalar quantization: ~4x smaller dense index in RAM,
                    # full-precision originals on disk for rescoring.
                    quantization_config=qm.ScalarQuantization(
                        scalar=qm.ScalarQuantizationConfig(
                            type=qm.ScalarType.INT8, quantile=0.99, always_ram=True
                        )
                    ),
                )
            except Exception as e:
                # Two concurrent first-ever ingests can race the create (409);
                # tolerate iff the collection now exists.
                existing = [c.name for c in client.get_collections().collections]
                if self._collection not in existing:
                    raise VectorStoreError("Failed to create collection", detail=str(e)) from e
                logger.info(f"[Qdrant] Concurrent creation of '{self._collection}' tolerated.")
            self._ensure_payload_indexes()
            return

        info = client.get_collection(self._collection)
        if not self._is_hybrid_schema(info):
            # Refuse to write into a legacy dense-only collection.
            raise SchemaMigrationError(
                f"Collection '{self._collection}' predates the hybrid schema. "
                f"Reset it (or delete the qdrant volume) and re-ingest."
            )
        self._ensure_payload_indexes()

    # --- writes ---------------------------------------------------------------

    def upsert(self, records: Sequence[VectorRecord]) -> None:
        self.ensure_ready()
        if not records:
            logger.warning("[Qdrant] No vectors to upsert.")
            return

        sparse_vectors = self._sparse_documents([r.text for r in records])

        points = []
        # strict=True: records and sparse vectors are produced 1:1; a length
        # mismatch would silently pair a chunk with another chunk's vector.
        for i, (record, sparse) in enumerate(zip(records, sparse_vectors, strict=True)):
            if len(record.embedding) != self._settings.embed_dim:
                raise VectorStoreError(
                    f"Embedding size {len(record.embedding)} does not match expected "
                    f"{self._settings.embed_dim} for chunk: {record.text[:50]!r}"
                )
            meta = record.metadata or {}
            points.append(
                qm.PointStruct(
                    id=make_point_id(
                        source=meta.get("source", "unknown"),
                        etag=meta.get("etag", ""),
                        chunk_seq=meta.get("chunk_seq", i),
                    ),
                    vector={DENSE_VECTOR: record.embedding, SPARSE_VECTOR: sparse},
                    payload={"text": record.text, **meta},
                )
            )
        logger.info(f"[Qdrant] Upserting {len(points)} vectors.")
        try:
            self._get_client().upsert(collection_name=self._collection, points=points)
        except Exception as e:
            raise VectorStoreError("Upsert failed", detail=str(e)) from e

    # --- reads ------------------------------------------------------------------

    @staticmethod
    def _source_filter(filter_sources: list[str] | None) -> qm.Filter | None:
        if not filter_sources:
            return None
        return qm.Filter(
            must=[qm.FieldCondition(key="source", match=qm.MatchAny(any=filter_sources))]
        )

    def hybrid_search(self, dense_vector: list[float], query_text: str,
                      k: int, filter_sources: list[str] | None = None) -> list[ScoredChunk]:
        """Dense + BM25 legs fused with Reciprocal Rank Fusion.

        No get_collections() pre-flight: it cost an extra round-trip on every
        query, and — being outside the try — let raw qdrant-client exceptions
        escape as unclassified 500s instead of VectorStoreError (502). A
        missing collection surfaces from query_points itself.
        """
        client = self._get_client()
        query_filter = self._source_filter(filter_sources)
        try:
            # Filter applied inside each prefetch so both legs only rank
            # candidates from the selected documents.
            prefetch = [
                qm.Prefetch(query=dense_vector, using=DENSE_VECTOR, limit=k, filter=query_filter),
                qm.Prefetch(query=self._sparse_query(query_text), using=SPARSE_VECTOR, limit=k,
                            filter=query_filter),
            ]
            response = client.query_points(
                collection_name=self._collection,
                prefetch=prefetch,
                query=qm.FusionQuery(fusion=qm.Fusion.RRF),
                limit=k,
                with_payload=True,
            )
        except Exception as e:
            raise VectorStoreError("Hybrid search failed", detail=str(e)) from e

        logger.info(f"[Qdrant] Hybrid search returned {len(response.points)} fused candidates.")
        return [
            ScoredChunk(
                point_id=str(p.id),
                score=float(p.score or 0.0),
                text=(p.payload or {}).get("text", ""),
                payload=p.payload or {},
            )
            for p in response.points
        ]

    def fetch_chunks_by_seq(self, source: str, seqs: list[int]) -> dict[int, str]:
        if not seqs:
            return {}
        flt = qm.Filter(
            must=[
                qm.FieldCondition(key="source", match=qm.MatchValue(value=source)),
                qm.FieldCondition(key="chunk_seq", match=qm.MatchAny(any=list(seqs))),
            ]
        )
        return self._scroll_texts(flt, limit=len(seqs))

    def fetch_section_chunks(self, source: str, section_title: str) -> dict[int, str]:
        """Capped at 500 chunks — callers assemble within a char budget, so a
        pathological 'section' (heading-less doc) cannot blow up memory."""
        flt = qm.Filter(
            must=[
                qm.FieldCondition(key="source", match=qm.MatchValue(value=source)),
                qm.FieldCondition(key="section_title", match=qm.MatchValue(value=section_title)),
            ]
        )
        return self._scroll_texts(flt, limit=500)

    def _scroll_texts(self, flt: qm.Filter, limit: int) -> dict[int, str]:
        """Shared payload-filtered scroll. Wrapping is not optional: these run
        on every query (context expansion), so an unwrapped client exception
        would escape as an unclassified 500 instead of VectorStoreError."""
        try:
            points, _ = self._get_client().scroll(
                collection_name=self._collection, scroll_filter=flt,
                with_payload=True, with_vectors=False, limit=limit,
            )
        except Exception as e:
            raise VectorStoreError("Chunk scroll failed", detail=str(e)) from e
        return {
            p.payload["chunk_seq"]: p.payload.get("text", "")
            for p in points if p.payload and "chunk_seq" in p.payload
        }

    # --- deletes -------------------------------------------------------------

    def _delete_by_filter(self, flt: qm.Filter) -> None:
        try:
            self._get_client().delete(
                collection_name=self._collection,
                points_selector=qm.FilterSelector(filter=flt),
            )
        except Exception as e:
            raise VectorStoreError("Delete failed", detail=str(e)) from e

    def _collection_exists(self) -> bool:
        """Existence probe that never leaks a raw client exception."""
        try:
            return self._get_client().collection_exists(self._collection)
        except Exception as e:
            raise VectorStoreError("Failed to query collection state", detail=str(e)) from e

    def delete_by_source(self, source: str) -> None:
        if not self._collection_exists():
            logger.warning(f"[Qdrant] Collection '{self._collection}' does not exist.")
            return
        logger.info(f"[Qdrant] Deleting vectors for source: {source}")
        self._delete_by_filter(
            qm.Filter(must=[qm.FieldCondition(key="source", match=qm.MatchValue(value=source))])
        )

    def delete_stale(self, source: str, current_etag: str) -> None:
        """Remove points of `source` whose etag differs — called AFTER the new
        version is upserted (staged swap: the document is never absent)."""
        if not self._collection_exists():
            return
        logger.info(f"[Qdrant] Deleting stale vectors for {source} (keeping etag {current_etag!r})")
        self._delete_by_filter(
            qm.Filter(
                must=[qm.FieldCondition(key="source", match=qm.MatchValue(value=source))],
                must_not=[qm.FieldCondition(key="etag", match=qm.MatchValue(value=current_etag))],
            )
        )

    def reset(self) -> None:
        try:
            self._get_client().delete_collection(collection_name=self._collection)
        except Exception as e:
            raise VectorStoreError("Collection reset failed", detail=str(e)) from e
        self.ensure_ready()
