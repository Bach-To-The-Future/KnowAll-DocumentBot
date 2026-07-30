"""FastAPI dependency providers.

The ServiceContainer is built once in the lifespan and parked on app.state;
these providers surface it (and its members) to routers. Tests override
`get_container` — or construct services directly with fakes.
"""
import hmac
from typing import Optional

from fastapi import Depends, Header, Request

from core.config import Settings, get_settings
from core.exceptions import AuthenticationError, AuthorizationError
from core.interfaces import JobStore
from services.container import ServiceContainer
from services.ingestion import IngestionService
from services.query import QueryService

# Read-only surface reachable with a scoped query key (API_QUERY_KEYS).
READONLY_PATH_PREFIXES = ("/query", "/list_documents", "/ingest/status", "/stats")


def get_container(request: Request) -> ServiceContainer:
    return request.app.state.container


def get_settings_dep() -> Settings:
    return get_settings()


def get_query_service(container: ServiceContainer = Depends(get_container)) -> QueryService:
    return container.query


def get_ingestion_service(container: ServiceContainer = Depends(get_container)) -> IngestionService:
    return container.ingestion


def get_job_store(container: ServiceContainer = Depends(get_container)) -> JobStore:
    return container.job_store


def _matches(candidate: str, secret: str) -> bool:
    """Constant-time comparison, no timing side channel.

    Operands are encoded first: hmac.compare_digest() raises TypeError on
    non-ASCII *str* input, which turned any header like `X-API-Key: café`
    into a 500 + traceback instead of a clean 401.
    """
    return hmac.compare_digest(
        candidate.encode("utf-8", "ignore"),
        secret.encode("utf-8", "ignore"),
    )


def require_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(None),
    settings: Settings = Depends(get_settings_dep),
) -> None:
    """API_KEY grants full access; keys in API_QUERY_KEYS are limited to the
    read-only surface. Auth is enabled iff API_KEY is set; otherwise the API
    runs open (dev mode — flagged loudly at startup)."""
    if request.url.path == "/health":
        return  # liveness probes must not need credentials
    if not settings.api_key:
        return
    if not x_api_key:
        raise AuthenticationError("Invalid or missing API key.")
    if _matches(x_api_key, settings.api_key):
        return
    if any(_matches(x_api_key, key) for key in settings.query_keys):
        if request.url.path.startswith(READONLY_PATH_PREFIXES):
            return
        raise AuthorizationError("This API key is limited to query endpoints.")
    raise AuthenticationError("Invalid or missing API key.")
