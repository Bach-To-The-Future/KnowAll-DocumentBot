"""IngestionService: object validation, job lifecycle, and the
extract -> embed -> staged-upsert pipeline. Used by the API (create/queue),
the arq worker (execute), and the BackgroundTasks fallback."""
import logging
import os
import shutil
import tempfile
import uuid

from core.config import Settings
from core.constants import CORPUS_VERSION_KEY
from core.exceptions import ExtractionError, InvalidRequestError
from core.interfaces import CacheStore, ChunkLike, DenseEmbedder, JobStore, VectorStore
from core.model_identity import verify_embedding_model
from core.token_budget import check_embedding_budget
from integrations.object_storage import MinIOObjectStorage
from models.schemas import VectorRecord

logger = logging.getLogger(__name__)


def sanitize_object_name(object_name: str) -> str:
    """Collapse any client-supplied name to a bare filename.

    Blocks path traversal (e.g. '../../etc/x') when the name is used to
    build a local filesystem path.
    """
    base = os.path.basename((object_name or "").replace("\\", "/")).strip()
    if not base or base in {".", ".."} or "\x00" in base:
        raise InvalidRequestError(f"Invalid object name: {object_name!r}")
    return base


class IngestionService:
    def __init__(self, storage: MinIOObjectStorage, job_store: JobStore,
                 vector_store: VectorStore, embedder: DenseEmbedder,
                 cache: CacheStore, settings: Settings) -> None:
        self._storage = storage
        self._job_store = job_store
        self._vector_store = vector_store
        self._embedder = embedder
        self._cache = cache
        self._settings = settings

    # --- job lifecycle -----------------------------------------------------

    def create_job(self, bucket: str, object_name: str) -> dict[str, str]:
        """Fast in-request validation; heavy work goes to the queue.
        Raises ObjectNotFoundError / ObjectStorageError / InvalidRequestError."""
        # The client-supplied bucket is IGNORED. Honoring it allowed any
        # caller to read (and index, and then exfiltrate via chat answers)
        # arbitrary buckets on the same MinIO.
        bucket = self._pinned_bucket(bucket)
        file_name = sanitize_object_name(object_name)
        self._storage.ensure_bucket()
        etag = self._storage.head_etag(bucket, object_name)

        job_id = str(uuid.uuid4())
        self._job_store.update(job_id, status="queued", object_name=object_name, bucket=bucket)
        return {"job_id": job_id, "bucket": bucket, "object_name": object_name,
                "file_name": file_name, "etag": etag}

    def _pinned_bucket(self, requested: str) -> str:
        """Always the configured bucket; a mismatch is logged, never honored."""
        allowed = self._storage.bucket
        if requested and requested != allowed:
            logger.warning(
                f"Ignoring requested bucket {requested!r}; pinned to {allowed!r}."
            )
        return allowed

    def execute(self, job_id: str, bucket: str, object_name: str,
                file_name: str, etag: str) -> int:
        """Run one ingest. Marks running/completed but RAISES on failure —
        the caller (worker or fallback) owns retry-vs-fail semantics."""
        # Defense in depth: jobs enqueued before the pin (or by any future
        # producer) are still confined to the configured bucket.
        bucket = self._pinned_bucket(bucket)
        self._job_store.update(job_id, status="running")
        # Fresh temp dir per ingest: no collisions between concurrent jobs;
        # removed unconditionally afterwards.
        tmp_dir = tempfile.mkdtemp(prefix="knowall_ingest_")
        local_path = os.path.join(tmp_dir, file_name)
        try:
            self._vector_store.ensure_ready()
            self._storage.download_file(bucket, object_name, local_path)
            logger.info(f"[job {job_id}] Downloaded '{object_name}' to {local_path}")

            chunk_count = self.process_document(local_path, etag=etag)
            self._job_store.update(job_id, status="completed", chunks_embedded=chunk_count)
            logger.info(f"[job {job_id}] Embedded {chunk_count} chunks from '{object_name}'.")
            return chunk_count
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def run_fallback(self, job_id: str, bucket: str, object_name: str,
                     file_name: str, etag: str, trace_id: str = "-") -> None:
        """BackgroundTasks path (no Redis): single attempt, failure recorded.

        Phase 4.2: `trace_id` is defaulted so the signature stays compatible
        with callers that predate it, and appears in the failure line — this
        path has no DLQ, so the log IS the record.
        """
        try:
            self.execute(job_id, bucket, object_name, file_name, etag)
        except Exception as e:
            logger.exception(
                f"[job {job_id}] [trace {trace_id}] Ingestion failed for "
                f"'{object_name}'"
            )
            self._job_store.update(job_id, status="failed", error=str(e))

    # --- pipeline -------------------------------------------------------------

    def process_document(self, file_path: str, etag: str = "") -> int:
        """Extract, embed and store one document in bounded batches.

        Peak memory is O(batch) rather than O(document): each batch is
        embedded, upserted, then dropped. Previously a large CSV held every
        chunk, every 768-float embedding and every payload simultaneously.
        """
        # Imported here so worker/API share the registry without a hard
        # dependency at module import time.
        from extraction.options import ExtractStrategy

        extractor = ExtractStrategy.get_extractor(file_path)
        source = os.path.basename(file_path)

        logger.info(f"Using extractor: {extractor.__class__.__name__}")
        nodes = list(extractor.extract_and_chunk(file_path))
        total_chunks = len(nodes)
        logger.info(f"Extracted {total_chunks} chunks")
        if not nodes:
            raise ExtractionError(f"No content could be extracted from '{source}'.")

        # Fail loudly and early rather than OOM-killing the worker halfway
        # through writing a partial document.
        limit = self._settings.max_chunks_per_document
        if total_chunks > limit:
            raise ExtractionError(
                f"'{source}' produced {total_chunks} chunks, over the limit of {limit}. "
                f"Split the document or raise MAX_CHUNKS_PER_DOCUMENT."
            )

        # Resolved once per document, not per batch: one /api/tags call, and a
        # model swapped mid-document would be caught on the next one rather
        # than producing a document whose chunks disagree with each other.
        embed_digest = verify_embedding_model(self._settings, context="ingest")

        batch_size = self._settings.ingest_batch_size
        embedded = 0
        for start in range(0, total_chunks, batch_size):
            batch = nodes[start:start + batch_size]
            # Document-wide sequence + etag feed the deterministic point IDs
            # (uuid5 of source:etag:chunk_seq) that make upserts idempotent.
            # Numbering is global, so batching does not change any point ID.
            for offset, node in enumerate(batch):
                node.metadata["chunk_seq"] = start + offset
                node.metadata["etag"] = etag
                # Finding #2 / phase 2.1: every point records which embedding
                # model produced its vector. Without this, a republished tag
                # leaves a collection silently mixing vectors from two models
                # and nothing downstream can tell.
                node.metadata["embed_model"] = self._settings.embed_model
                node.metadata["embed_model_digest"] = embed_digest or "unknown"

            records = self._embed_chunks(batch)
            if records:
                self._vector_store.upsert(records)
                embedded += len(records)
            logger.info(
                f"[{source}] batch {start // batch_size + 1}: "
                f"{embedded}/{total_chunks} chunks indexed"
            )
            # Drop this batch's vectors before building the next one. Nodes
            # are released too so long documents shed memory as they go.
            nodes[start:start + batch_size] = [None] * len(batch)  # type: ignore[list-item]
            del records, batch

        if embedded == 0:
            raise ExtractionError(f"'{source}' produced no non-empty chunks.")

        # Staged swap: every new-etag point is written above, so dropping
        # older etags now is the atomic cut-over. A crash at any point leaves
        # either version fully queryable — never a gap.
        self._vector_store.delete_stale(source, current_etag=etag)

        self._cache.incr(CORPUS_VERSION_KEY)  # invalidate cached answers
        return embedded

    def _embed_chunks(self, nodes: list[ChunkLike]) -> list[VectorRecord]:
        filtered = [n for n in nodes if n.text and n.text.strip()]
        # Finding #19: FAIL LOUD before embedding. Ollama truncates at 2048
        # tokens and returns HTTP 200 with a well-formed 768-dim vector built
        # from a prefix — a wrong vector nothing downstream can detect. Raising
        # here fails the ingest job, which is recoverable; a silently wrong
        # vector in the index is not.
        for node in filtered:
            check_embedding_budget(
                node.text, source=str(node.metadata.get("source", "chunk")))
        texts = [n.text for n in filtered]
        if not texts:
            return []
        embeddings = self._embedder.embed_documents(texts)
        # Hard guarantee against text<->vector misalignment before pairing
        # (embedders also enforce this; belt and braces at the pairing site).
        if len(embeddings) != len(filtered):
            raise ExtractionError(
                f"Embedding count mismatch: {len(embeddings)} embeddings for {len(filtered)} chunks."
            )
        return [
            VectorRecord(embedding=emb, text=node.text, metadata=dict(node.metadata))
            # strict=True mirrors the explicit count check above; both guard
            # the text<->vector alignment invariant.
            for node, emb in zip(filtered, embeddings, strict=True)
        ]

    # --- deletion ---------------------------------------------------------------

    def delete_document(self, object_name: str) -> None:
        """Remove one document from object storage AND the vector index."""
        self._storage.delete_object(object_name)
        # Vectors are keyed by sanitized basename (the ingest contract), not
        # the raw MinIO key — a prefixed key would orphan its vectors.
        self._vector_store.delete_by_source(sanitize_object_name(object_name))
        self._cache.incr(CORPUS_VERSION_KEY)
