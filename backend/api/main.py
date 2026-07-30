"""Application factory. All state lives on app.state, built and torn down by
the lifespan context manager; nothing connects at import time."""
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from api.dependencies import require_api_key
from api.errors import register_exception_handlers
from api.routers import documents, query, system
from core.config import Settings, get_settings
from integrations.llm_clients import ollama_model_available
from services.container import build_container

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if not settings.api_key:
        logger.warning("API_KEY is not set — API authentication is DISABLED. "
                       "Set API_KEY in .env to secure all endpoints.")

    # Composition root: wire integrations into services (pure, no I/O).
    app.state.container = build_container(settings)

    # Durable queue: enqueue to arq when Redis is configured; otherwise fall
    # back to in-process BackgroundTasks (single attempt, volatile status).
    app.state.arq_pool = None
    if settings.redis_url:
        try:
            from arq import create_pool
            from arq.connections import RedisSettings

            app.state.arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
            logger.info("Ingestion queue: arq/Redis (durable)")
        except Exception as e:
            logger.error(f"Failed to connect arq pool ({e}); falling back to BackgroundTasks.")
    else:
        logger.warning("REDIS_URL unset — ingestion uses in-process BackgroundTasks (not durable).")

    # One-time model availability check (non-fatal: the ollama container may
    # still be pulling models on first boot).
    if not settings.use_openai_embedding and not ollama_model_available(settings, settings.embed_model):
        logger.error(f"Embedding model '{settings.embed_model}' not available in Ollama at startup.")
    if not settings.use_openai_llm and not ollama_model_available(settings, settings.llm_model):
        logger.error(f"LLM model '{settings.llm_model}' not available in Ollama at startup.")

    # Warm retrieval models (no-op when baked into the image); threadpool so
    # a slow download doesn't block the event loop.
    try:
        container = app.state.container
        await run_in_threadpool(container.vector_store.get_sparse_model)  # type: ignore[attr-defined]
        await run_in_threadpool(container.reranker.warm)  # type: ignore[attr-defined]
    except Exception as e:
        logger.error(f"Failed to warm retrieval models: {e}")

    yield

    # Release pooled httpx/OpenAI connections held by the LLM client.
    try:
        await app.state.container.llm.aclose()
    except Exception as e:
        logger.warning(f"LLM client shutdown failed: {e}")
    if app.state.arq_pool is not None:
        await app.state.arq_pool.close()


def create_app() -> FastAPI:
    # The auth dependency applies to every route, including the routers.
    app = FastAPI(title="KnowAll DocumentBot", lifespan=lifespan,
                  dependencies=[Depends(require_api_key)])
    register_exception_handlers(app)
    app.include_router(system.router)
    app.include_router(query.router)
    app.include_router(documents.router)
    _register_rate_limiter(app, get_settings())
    return app


def _client_identity(request: Request, settings: Settings) -> str:
    """Identity to rate-limit on.

    request.client.host is the Next.js container for every browser request,
    so keying on it made the limit global — one user could exhaust the budget
    for everyone. The proxy authenticates the user and forwards X-User-Id
    (falling back to X-Forwarded-For); both are trustworthy only because
    reaching this API at all requires an API key that only the proxy holds.
    """
    if settings.trust_proxy_identity:
        user_id = request.headers.get("x-user-id")
        if user_id:
            return f"user:{user_id}"
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # Left-most entry is the originating client.
            return f"ip:{forwarded.split(',')[0].strip()}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


def _register_rate_limiter(app: FastAPI, settings: Settings) -> None:
    """Fixed-window limiter in Redis via the CacheStore.

    Shared across replicas: the previous in-process dict multiplied the
    effective limit by the replica count and leaked one key per client.
    """

    @app.middleware("http")
    async def rate_limit_queries(request: Request, call_next):
        limit = settings.rate_limit_per_minute
        if limit > 0 and request.url.path.startswith("/query"):
            identity = _client_identity(request, settings)
            window = int(time.time()) // 60  # fixed 60s window
            key = f"ratelimit:{identity}:{window}"
            cache = request.app.state.container.cache
            # Blocking Redis call — one round-trip, off the event loop.
            count = await run_in_threadpool(cache.incr_window, key, 120)
            if count > limit:
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"Rate limit exceeded: {limit} queries/minute."},
                    headers={"Retry-After": "60"},
                )
        return await call_next(request)


app = create_app()
