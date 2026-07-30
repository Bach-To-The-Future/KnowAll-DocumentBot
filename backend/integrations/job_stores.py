"""JobStore implementations: Redis (durable, shared API<->worker) and
in-memory (dev fallback, volatile)."""
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from core.config import Settings
from core.interfaces import JobStore

logger = logging.getLogger(__name__)

JOB_TTL_SECONDS = 7 * 24 * 3600


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InMemoryJobStore(JobStore):
    def __init__(self, max_tracked: int = 200) -> None:
        self._max_tracked = max_tracked
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.setdefault(job_id, {"job_id": job_id})
            job.update(fields, updated_at=_now())
            # Evict oldest TERMINAL jobs only: queued/running stay pollable.
            while len(self._jobs) > self._max_tracked:
                evictable = next(
                    (jid for jid, j in self._jobs.items()
                     if jid != job_id and j.get("status") in ("completed", "failed")),
                    None,
                )
                if evictable is None:
                    break
                self._jobs.pop(evictable)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def list_jobs(self, limit: int = 1000) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(job) for job in list(self._jobs.values())[:limit]]


class RedisJobStore(JobStore):
    def __init__(self, url: str) -> None:
        import redis  # dependency of arq

        self._redis = redis.Redis.from_url(url, decode_responses=True)
        self._redis.ping()

    @staticmethod
    def _key(job_id: str) -> str:
        return f"ingest:job:{job_id}"

    def update(self, job_id: str, **fields: Any) -> None:
        key = self._key(job_id)
        raw = self._redis.get(key)
        job = json.loads(raw) if raw else {"job_id": job_id}
        job.update(fields, updated_at=_now())
        self._redis.set(key, json.dumps(job, default=str), ex=JOB_TTL_SECONDS)

    def get(self, job_id: str) -> dict[str, Any] | None:
        raw = self._redis.get(self._key(job_id))
        return json.loads(raw) if raw else None

    def list_jobs(self, limit: int = 1000) -> list[dict[str, Any]]:
        """SCAN (never KEYS — it blocks the server) + batched MGET."""
        jobs: list[dict[str, Any]] = []
        try:
            keys: list[str] = []
            for key in self._redis.scan_iter(match=f"{self._key('')}*", count=200):
                keys.append(key)
                if len(keys) >= limit:
                    break
            for start in range(0, len(keys), 100):
                for raw in self._redis.mget(keys[start:start + 100]):
                    if not raw:
                        continue
                    try:
                        jobs.append(json.loads(raw))
                    except (TypeError, ValueError):
                        continue  # a poisoned record must not break the sweep
        except Exception as e:
            logger.warning(f"Job listing failed ({e}); returning what we have.")
        return jobs


def build_job_store(settings: Settings) -> JobStore:
    if settings.redis_url:
        try:
            store: JobStore = RedisJobStore(settings.redis_url)
            logger.info("Job store: Redis (durable)")
            return store
        except Exception as e:
            logger.warning(f"Redis job store unavailable ({e}); using in-memory fallback.")
    logger.warning("Job store: in-memory — statuses are lost on restart.")
    return InMemoryJobStore()
