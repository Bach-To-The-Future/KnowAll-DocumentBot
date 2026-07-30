"""Document lifecycle transport: upload, ingest, status, delete, list."""
import logging
import tempfile

from fastapi import APIRouter, BackgroundTasks, Depends, File, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from api.dependencies import (
    get_container,
    get_ingestion_service,
    get_job_store,
    get_settings_dep,
)
from arq.constants import default_queue_name

from core.config import Settings
from core.exceptions import JobNotFoundError, PayloadTooLargeError, ServiceOverloadedError
from core.interfaces import JobStore
from models.schemas import DeleteDocumentsRequest, IngestAccepted, MinIOIngestRequest
from services.container import ServiceContainer
from services.ingestion import IngestionService, sanitize_object_name

READ_CHUNK_BYTES = 1 << 20  # 1 MiB
SPOOL_MAX_BYTES = 8 << 20   # keep small uploads in RAM, spill larger to disk

logger = logging.getLogger(__name__)

router = APIRouter(tags=["documents"])


async def _assert_queue_has_room(pool, settings: Settings) -> None:
    """Shed load before accepting more work.

    Without this the queue grows without bound: uploads keep returning 202
    while the worker falls further behind, until Redis memory or the host
    OOM-killer decides the outcome.
    """
    if pool is None:
        return
    try:
        depth = await pool.zcard(default_queue_name)
    except Exception as e:
        logger.warning(f"Queue depth check failed ({e}); accepting the job.")
        return
    if depth >= settings.max_queue_depth:
        raise ServiceOverloadedError(
            f"Ingestion queue is saturated ({depth} pending). Retry shortly.",
            retry_after=60,
        )


async def _queue(request: Request, background_tasks: BackgroundTasks,
                 ingestion: IngestionService, bucket: str, object_name: str,
                 settings: Settings) -> IngestAccepted:
    pool = request.app.state.arq_pool
    await _assert_queue_has_room(pool, settings)
    # create_job does blocking MinIO + Redis I/O; this coroutine must not.
    job = await run_in_threadpool(ingestion.create_job, bucket, object_name)
    if pool is not None:  # durable queue
        await pool.enqueue_job(
            "ingest_document", job["job_id"], job["bucket"], job["object_name"],
            job["file_name"], job["etag"],
        )
    else:  # dev fallback: in-process, single attempt
        background_tasks.add_task(
            ingestion.run_fallback, job["job_id"], job["bucket"], job["object_name"],
            job["file_name"], job["etag"],
        )
    return IngestAccepted(
        job_id=job["job_id"], status="queued", status_url=f"/ingest/status/{job['job_id']}"
    )


@router.post("/upload/", status_code=202, response_model=IngestAccepted)
async def upload(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    container: ServiceContainer = Depends(get_container),
    settings: Settings = Depends(get_settings_dep),
):
    object_name = sanitize_object_name(file.filename or "")
    max_bytes = settings.max_upload_bytes

    # Stream the body through a bounded spool, counting as we go. Content-Length
    # is only a hint (and absent on chunked encodings), so the ceiling has to be
    # enforced on bytes actually read — before anything reaches MinIO.
    with tempfile.SpooledTemporaryFile(max_size=SPOOL_MAX_BYTES) as buffer:
        size = 0
        while chunk := await file.read(READ_CHUNK_BYTES):
            size += len(chunk)
            if size > max_bytes:
                raise PayloadTooLargeError(
                    f"Upload exceeds the maximum size of {max_bytes} bytes."
                )
            buffer.write(chunk)
        buffer.seek(0)

        # boto3 is blocking: keep it off the event loop (this endpoint is async).
        await run_in_threadpool(container.storage.ensure_bucket)
        await run_in_threadpool(container.storage.upload_fileobj, buffer, object_name)

    logger.info(f"Uploaded '{object_name}' ({size} bytes) to MinIO")
    return await _queue(request, background_tasks, container.ingestion,
                        container.storage.bucket, object_name, settings)


@router.post("/ingest_from_minio", status_code=202, response_model=IngestAccepted)
async def ingest_from_minio(
    request: Request,
    req: MinIOIngestRequest,
    background_tasks: BackgroundTasks,
    ingestion: IngestionService = Depends(get_ingestion_service),
    settings: Settings = Depends(get_settings_dep),
):
    return await _queue(request, background_tasks, ingestion,
                        req.bucket, req.object_name, settings)


@router.get("/ingest/status/{job_id}")
async def ingest_status(job_id: str, job_store: JobStore = Depends(get_job_store)):
    # Sync redis-py client: polled every 2s per tracked job, so a blocking
    # call here would stall the whole event loop under a burst of uploads.
    job = await run_in_threadpool(job_store.get, job_id)
    if job is None:
        raise JobNotFoundError(f"Unknown job: {job_id}")
    return job


@router.delete("/delete_documents")
def delete_documents(
    payload: DeleteDocumentsRequest,
    container: ServiceContainer = Depends(get_container),
):
    deleted: list[str] = []
    errors: list[dict[str, str]] = []
    container.storage.ensure_bucket()
    # Batch semantics: partial success is reported per file, not as a 5xx.
    for object_name in payload.object_names:
        try:
            container.ingestion.delete_document(object_name)
            deleted.append(object_name)
            logger.info(f"Deleted '{object_name}' from MinIO and Qdrant.")
        except Exception as e:
            logger.error(f"Failed to delete '{object_name}': {e}")
            errors.append({"file": object_name, "error": str(e)})
    return {
        "deleted": deleted,
        "errors": errors,
        "message": f"Deleted {len(deleted)} file(s), {len(errors)} error(s).",
    }


@router.get("/list_documents")
def list_documents(container: ServiceContainer = Depends(get_container)):
    container.storage.ensure_bucket()
    files = container.storage.list_keys()
    logger.info(f"Listed {len(files)} files from MinIO")
    return {"files": files}
