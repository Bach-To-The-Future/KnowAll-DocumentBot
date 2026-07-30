"""arq ingestion worker.

Resilience model:
  * The ingest payload runs in a SUBPROCESS pool, not a thread. Threads
    cannot be interrupted, so a hung extraction (malformed PDF, runaway OCR)
    previously leaked a thread and its temp dir forever while arq believed
    the slot was free. Processes can be killed, so job_timeout is real.
  * Permanently failed jobs are pushed to a Redis dead-letter list instead of
    vanishing after the last retry.
  * A startup sweep fails any job left "running" by a SIGKILL, so the tracker
    never shows a job that no longer exists.

Multiprocessing note: the pool uses the "spawn" context and each child builds
its OWN ServiceContainer in an initializer. Qdrant/Redis/boto3 clients are
not picklable and must never be inherited across a fork — only primitives
cross the process boundary.

Run with: arq worker.WorkerSettings
"""
import asyncio
import json
import logging
import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Any, Optional

from arq import Retry
from arq.connections import RedisSettings

from core.config import Settings, get_settings
from services.container import ServiceContainer, build_container

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_TRIES = 3
DLQ_KEY = "arq:dlq"
DLQ_MAX_LEN = 1000
DLQ_TTL = 30 * 24 * 3600

_settings = get_settings()

# --- parent process: bookkeeping only (job store, DLQ) ----------------------

_container: Optional[ServiceContainer] = None


def get_container() -> ServiceContainer:
    global _container
    if _container is None:
        _container = build_container(_settings)
    return _container


# --- child processes: the actual ingest work --------------------------------

_child_container: Optional[ServiceContainer] = None


def _child_init() -> None:
    """Runs once per pool process. Builds clients INSIDE the child so no
    socket or lock is inherited from the parent."""
    global _child_container
    logging.basicConfig(level=logging.INFO)
    _child_container = build_container(get_settings())


def _run_ingest(job_id: str, bucket: str, object_name: str,
                file_name: str, etag: str) -> int:
    """Executed in a pool subprocess.

    Module-level function with primitive arguments only — that is what makes
    it picklable. Returns the chunk count; exceptions propagate back to the
    parent through the future.
    """
    global _child_container
    if _child_container is None:  # defensive: initializer should have run
        _child_init()
    assert _child_container is not None
    return _child_container.ingestion.execute(job_id, bucket, object_name, file_name, etag)


# --- pool lifecycle ----------------------------------------------------------

_pool: Optional[ProcessPoolExecutor] = None


def _get_pool(settings: Settings) -> ProcessPoolExecutor:
    global _pool
    if _pool is None:
        logger.info(f"Starting ingest pool with {settings.worker_processes} process(es)")
        _pool = ProcessPoolExecutor(
            max_workers=settings.worker_processes,
            initializer=_child_init,
            mp_context=multiprocessing.get_context("spawn"),
        )
    return _pool


def _kill_pool() -> None:
    """Hard-terminate every child and drop the pool.

    ProcessPoolExecutor exposes no public API to kill a running task, so the
    private `_processes` map is used deliberately: a stuck child must die,
    and shutdown(cancel_futures=True) alone does not touch running work. The
    pool is rebuilt lazily on the next job (children reload their models).
    """
    global _pool
    if _pool is None:
        return
    for proc in list(getattr(_pool, "_processes", {}).values()):
        try:
            proc.kill()
        except Exception:  # already dead
            pass
    try:
        _pool.shutdown(wait=False, cancel_futures=True)
    except Exception:
        pass
    _pool = None
    logger.warning("Ingest pool killed and reset.")


def _dead_letter(container: ServiceContainer, job_id: str, payload: dict[str, Any],
                 error: str) -> None:
    """Failed jobs land here instead of disappearing after the last retry."""
    container.cache.list_push_trim(
        DLQ_KEY,
        json.dumps({"job_id": job_id, "failed_at": time.time(), "error": error, **payload},
                   default=str),
        max_len=DLQ_MAX_LEN,
        ttl_seconds=DLQ_TTL,
    )
    logger.error(f"[job {job_id}] Dead-lettered: {error}")


# --- arq hooks ----------------------------------------------------------------

async def startup(ctx: dict) -> None:
    """Sweep jobs orphaned by a hard restart.

    A SIGKILL mid-ingest leaves status="running" forever; without this the UI
    polls a job that no process is working on.
    """
    container = get_container()
    swept = 0
    for job in await asyncio.to_thread(container.job_store.list_jobs, 1000):
        # ONLY "running": a job in that state was executing inside a process
        # that no longer exists. "retrying" jobs are durably deferred in arq
        # and will run again — sweeping them would both lie about their status
        # and dead-letter them a second time when the real retry finally fails.
        if job.get("status") == "running":
            job_id = job.get("job_id")
            if not job_id:
                continue
            container.job_store.update(
                job_id, status="failed",
                error="Worker restarted while this job was in flight.",
            )
            _dead_letter(container, job_id, job, "orphaned by worker restart")
            swept += 1
    if swept:
        logger.warning(f"Startup sweep: failed {swept} orphaned job(s).")
    else:
        logger.info("Startup sweep: no orphaned jobs.")


async def shutdown(ctx: dict) -> None:
    _kill_pool()


async def ingest_document(ctx: dict, job_id: str, bucket: str, object_name: str,
                          file_name: str, etag: str) -> None:
    container = get_container()
    payload = {"bucket": bucket, "object_name": object_name, "etag": etag}
    attempt = ctx.get("job_try", 1)
    loop = asyncio.get_running_loop()

    try:
        future = loop.run_in_executor(
            _get_pool(_settings), _run_ingest, job_id, bucket, object_name, file_name, etag
        )
        # wait_for cancels the wrapper, not the child — the kill below is what
        # actually reclaims the process, its memory and its temp directory.
        await asyncio.wait_for(future, timeout=_settings.ingest_job_timeout)
        return
    except asyncio.TimeoutError:
        _kill_pool()
        error = f"Ingestion exceeded {_settings.ingest_job_timeout}s and was terminated."
        logger.error(f"[job {job_id}] {error}")
    except Exception as e:
        error = str(e)
        logger.exception(f"[job {job_id}] Ingestion attempt {attempt} failed")
        # A dead child (OOM kill) poisons the pool for every queued job.
        if isinstance(e, BrokenProcessPool):
            _kill_pool()

    if attempt >= MAX_TRIES:
        container.job_store.update(job_id, status="failed", error=error, attempts=attempt)
        _dead_letter(container, job_id, payload, error)
        return  # recorded + dead-lettered; do not re-raise into arq

    backoff = 30 * attempt  # linear: 30s, 60s
    container.job_store.update(job_id, status="retrying", error=error, attempts=attempt)
    logger.warning(f"[job {job_id}] Attempt {attempt} failed, retrying in {backoff}s: {error}")
    raise Retry(defer=backoff)


class WorkerSettings:
    functions = [ingest_document]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(_settings.redis_url or "redis://localhost:6379/0")
    # Concurrency is bounded by the subprocess pool, not by arq: one in-flight
    # arq task per pool slot keeps queue accounting honest.
    max_jobs = _settings.worker_processes
    # arq's own ceiling sits above ours so our kill path runs first and can
    # record a proper failure/DLQ entry.
    job_timeout = _settings.ingest_job_timeout + 60
    max_tries = MAX_TRIES
    keep_result = 3600
