"""Query transport.

Endpoints are `async def`: retrieval is blocking, so prepare() is handed to a
worker thread, while generation awaits natively on httpx. That combination is
what keeps a 40-second answer from occupying an anyio threadpool slot.

Admission control bounds in-flight queries explicitly. Without it, load past
the (invisible) threadpool ceiling queued indefinitely until liveness probes
timed out and the container was restarted mid-flight.
"""
import asyncio
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from api.dependencies import get_query_service
from core.config import get_settings
from core.exceptions import ServiceOverloadedError
from models.schemas import QueryRequest, QueryResponse
from services.query import PreparedQuery, QueryService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["query"])

# Module-level: asyncio primitives created outside a loop are loop-agnostic
# in 3.10+, and one ceiling per process is exactly the intent.
_query_slots = asyncio.Semaphore(get_settings().max_concurrent_queries)


def _admit() -> None:
    """Reject immediately when saturated rather than queueing.

    locked() and acquire() are checked without an intervening await, so on a
    single-threaded loop this cannot race.
    """
    if _query_slots.locked():
        raise ServiceOverloadedError(
            "Too many concurrent queries; retry shortly.", retry_after=5
        )


@router.post("/query", response_model=QueryResponse)
async def ask_question(req: QueryRequest, service: QueryService = Depends(get_query_service)):
    _admit()
    await _query_slots.acquire()
    try:
        # Blocking: embedding, hybrid search, rerank, plus the short rewrite
        # and expansion completions.
        prepared = await run_in_threadpool(service.prepare, req)
        return await service.answer_prepared(prepared)
    finally:
        _query_slots.release()


@router.post("/query/stream")
async def ask_question_stream(req: QueryRequest,
                              service: QueryService = Depends(get_query_service)):
    """NDJSON stream: one citations line, token lines, then 'done'.

    prepare() runs HERE, before the StreamingResponse exists, so retrieval
    failures still travel through the exception handlers as real 4xx/5xx.
    Once the response starts, the status is committed and errors can only be
    in-band 'error' events.
    """
    _admit()
    await _query_slots.acquire()
    try:
        prepared = await run_in_threadpool(service.prepare, req)
    except BaseException:
        _query_slots.release()  # nothing was streamed; give the slot straight back
        raise

    async def guarded_stream(prepared: PreparedQuery) -> AsyncIterator[str]:
        # The slot is held for the whole stream and released exactly once,
        # including on client disconnect (the generator is aclose()d).
        try:
            async for line in service.stream_prepared(prepared):
                yield line
        finally:
            _query_slots.release()

    return StreamingResponse(
        guarded_stream(prepared), media_type="application/x-ndjson"
    )
