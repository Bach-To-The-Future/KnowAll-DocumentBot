"""Global exception handlers: domain errors -> standardized JSON.

Response shape: {"detail": <message>, "error": {"type", "message", "detail"}}.
`detail` is kept top-level for backward compatibility with FastAPI's
HTTPException shape (the Streamlit client and scripts read it).
"""
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.exceptions import RAGSystemError

logger = logging.getLogger(__name__)


def _envelope(exc_type: str, message: str, detail: str | None) -> dict:
    return {
        "detail": message,
        "error": {"type": exc_type, "message": message, "detail": detail},
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RAGSystemError)
    async def handle_domain_error(request: Request, exc: RAGSystemError) -> JSONResponse:
        log = logger.warning if exc.http_status < 500 else logger.error
        log(f"{type(exc).__name__} on {request.url.path}: {exc.message} ({exc.detail})")
        # Backpressure errors carry the client's retry budget.
        retry_after = getattr(exc, "retry_after", None)
        headers = {"Retry-After": str(retry_after)} if retry_after else None
        return JSONResponse(
            status_code=exc.http_status,
            content=_envelope(type(exc).__name__, exc.message, exc.detail),
            headers=headers,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Anything that escaped the domain hierarchy is a bug: log the full
        # traceback, return a generic 500 without leaking internals.
        logger.exception(f"Unhandled error on {request.url.path}")
        return JSONResponse(
            status_code=500,
            content=_envelope("InternalError", "Internal server error.", None),
        )
