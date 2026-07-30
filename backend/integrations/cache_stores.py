"""CacheStore implementations. Best-effort by contract: a cache outage must
never fail a request, so Redis errors degrade to misses with a log line.

Redis is the multi-replica implementation; InMemory is the single-process
dev fallback and is NOT correct across replicas (documented per method).
"""
import logging
import threading
import time
from collections import OrderedDict, deque
from typing import Deque

from core.config import Settings
from core.interfaces import CacheStore

logger = logging.getLogger(__name__)

MEM_MAX_ENTRIES = 512


class InMemoryCacheStore(CacheStore):
    """Single-process fallback. Rate limits and telemetry computed here are
    per-process — running >1 replica without Redis silently multiplies rate
    limits and shards the stats."""

    def __init__(self, max_entries: int = MEM_MAX_ENTRIES) -> None:
        self._max_entries = max_entries
        self._data: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._counters: dict[str, tuple[float, int]] = {}
        self._lists: dict[str, Deque[str]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            expires_at, value = item
            if time.time() > expires_at:
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return value

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        with self._lock:
            self._data[key] = (time.time() + ttl_seconds, value)
            self._data.move_to_end(key)
            while len(self._data) > self._max_entries:
                self._data.popitem(last=False)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def incr(self, key: str) -> int:
        with self._lock:
            _, current = self._counters.get(key, (float("inf"), 0))
            value = current + 1
            self._counters[key] = (float("inf"), value)
            # A corpus-version bump invalidates everything in this process.
            self._data.clear()
            return value

    def incr_window(self, key: str, ttl_seconds: int) -> int:
        with self._lock:
            now = time.time()
            expires_at, current = self._counters.get(key, (0.0, 0))
            if now > expires_at:  # window rolled over
                expires_at, current = now + ttl_seconds, 0
            value = current + 1
            self._counters[key] = (expires_at, value)
            return value

    def list_push_trim(self, key: str, value: str, max_len: int, ttl_seconds: int) -> None:
        with self._lock:
            bucket = self._lists.get(key)
            if bucket is None or bucket.maxlen != max_len:
                bucket = deque(bucket or (), maxlen=max_len)
                self._lists[key] = bucket
            bucket.appendleft(value)  # deque(maxlen) drops the oldest for us

    def list_range(self, key: str, count: int) -> list[str]:
        with self._lock:
            return list(self._lists.get(key, deque()))[:count]


class RedisCacheStore(CacheStore):
    def __init__(self, url: str) -> None:
        import redis  # dependency of arq

        self._redis = redis.Redis.from_url(url, decode_responses=True)
        self._redis.ping()

    def get(self, key: str) -> str | None:
        try:
            return self._redis.get(key)
        except Exception as e:
            logger.warning(f"Cache get failed ({e}); treating as miss.")
            return None

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        try:
            self._redis.setex(key, ttl_seconds, value)
        except Exception as e:
            logger.warning(f"Cache set failed ({e}); skipping.")

    def delete(self, key: str) -> None:
        try:
            self._redis.delete(key)
        except Exception as e:
            logger.warning(f"Cache delete failed ({e}); skipping.")

    def incr(self, key: str) -> int:
        try:
            return int(self._redis.incr(key))
        except Exception as e:
            logger.warning(f"Cache incr failed ({e}).")
            return 0

    def incr_window(self, key: str, ttl_seconds: int) -> int:
        """Fixed window: INCR, then EXPIRE only when the key has no TTL, so
        later hits inside the same window don't push the expiry forward.
        One pipelined round-trip in the common case."""
        try:
            pipe = self._redis.pipeline()
            pipe.incr(key)
            pipe.ttl(key)
            count, ttl = pipe.execute()
            if ttl is not None and int(ttl) < 0:  # first hit of this window
                self._redis.expire(key, ttl_seconds)
            return int(count)
        except Exception as e:
            # Fail OPEN: a Redis outage must not lock every user out.
            logger.warning(f"Rate-limit counter failed ({e}); allowing request.")
            return 0

    def list_push_trim(self, key: str, value: str, max_len: int, ttl_seconds: int) -> None:
        try:
            pipe = self._redis.pipeline()
            pipe.lpush(key, value)
            pipe.ltrim(key, 0, max_len - 1)
            pipe.expire(key, ttl_seconds)
            pipe.execute()
        except Exception as e:
            logger.warning(f"Telemetry push failed ({e}); dropping sample.")

    def list_range(self, key: str, count: int) -> list[str]:
        try:
            return list(self._redis.lrange(key, 0, count - 1))
        except Exception as e:
            logger.warning(f"Telemetry read failed ({e}); returning empty.")
            return []


def build_cache_store(settings: Settings) -> CacheStore:
    if settings.redis_url:
        try:
            store: CacheStore = RedisCacheStore(settings.redis_url)
            logger.info("Cache store: Redis (shared across replicas)")
            return store
        except Exception as e:
            logger.warning(f"Redis cache unavailable ({e}); using in-memory fallback.")
    logger.warning(
        "Cache store: in-memory — session memory, rate limiting and telemetry "
        "are PER-PROCESS. Do not run more than one replica in this mode."
    )
    return InMemoryCacheStore()
