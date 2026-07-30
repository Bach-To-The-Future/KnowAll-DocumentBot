"""Operational endpoints: liveness + rolling stats."""
from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from api.dependencies import get_container
from services.container import ServiceContainer

router = APIRouter(tags=["system"])


@router.get("/health")
async def health():
    """Liveness probe (auth-exempt). Deliberately shallow: dependency health
    is each service's own healthcheck's job; a deep check here would flap."""
    return {"status": "ok"}


@router.get("/stats")
async def stats(container: ServiceContainer = Depends(get_container)):
    """Rolling stats over the last ~500 queries ACROSS ALL REPLICAS (the
    window lives in Redis): per-stage latency percentiles, cache hit rate,
    and the abstention rate — the leading indicator that the rerank score
    floor needs recalibration."""
    return await run_in_threadpool(container.telemetry.rolling_stats)
