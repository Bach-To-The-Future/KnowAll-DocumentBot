"""Operational endpoints: liveness, readiness + rolling stats."""
from fastapi import APIRouter, Depends, Response, status
from starlette.concurrency import run_in_threadpool

from api.dependencies import get_container
from services.container import ServiceContainer

router = APIRouter(tags=["system"])


@router.get("/health")
async def health():
    """Liveness probe (auth-exempt). Deliberately shallow: dependency health
    is each service's own healthcheck's job; a deep check here would flap."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(response: Response,
                container: ServiceContainer = Depends(get_container)):
    """Readiness probe (phase 2.6). FAILS when a required payload index is
    missing.

    Deeper than /health on purpose. A missing payload index is not a liveness
    problem — the API answers fine — but filtered retrieval silently falls back
    to a full scan and degrades as the collection grows. Nothing else in the
    system would ever report it, so readiness is where it belongs: a replica
    that will serve slow, silently-degrading queries should not take traffic.
    """
    missing = await run_in_threadpool(container.vector_store.missing_payload_indexes)
    if missing:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "degraded",
            "missing_payload_indexes": missing,
            "detail": (
                "Filtered retrieval on these fields will FULL SCAN. Recreate "
                "them (restarting the API calls ensure_ready, which does) "
                "before serving traffic."
            ),
        }
    return {"status": "ready"}


@router.get("/stats")
async def stats(container: ServiceContainer = Depends(get_container)):
    """Rolling stats over the last ~500 queries ACROSS ALL REPLICAS (the
    window lives in Redis): per-stage latency percentiles, cache hit rate,
    and the abstention rate — the leading indicator that the rerank score
    floor needs recalibration."""
    return await run_in_threadpool(container.telemetry.rolling_stats)
