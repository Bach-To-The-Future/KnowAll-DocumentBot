"""Structured telemetry.

Two channels:
  * log_event()  — one JSON line per event on stdout (greppable, shippable).
  * Telemetry    — a bounded ring buffer in the CacheStore so /stats reports
                   GLOBAL numbers across replicas. The in-process deque this
                   replaced made every replica report its own shard.
"""
import json
import logging
import time
import uuid
from contextlib import contextmanager
from typing import Iterator

from core.interfaces import CacheStore

_logger = logging.getLogger("telemetry")
if not _logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))  # raw JSON line
    _logger.addHandler(_handler)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False  # keep JSON lines out of the root logger's format

TELEMETRY_KEY = "telemetry:queries"
WINDOW_SIZE = 500
WINDOW_TTL = 24 * 3600

_TIMING_KEYS = ("rewrite_ms", "expansion_ms", "retrieval_ms", "generation_ms")


def new_trace_id() -> str:
    return uuid.uuid4().hex[:12]


def log_event(event: str, **fields: object) -> None:
    payload = {"event": event, "ts": round(time.time(), 3), **fields}
    _logger.info(json.dumps(payload, ensure_ascii=False, default=str))


@contextmanager
def timed(sink: dict, key: str) -> Iterator[None]:
    """Context manager that writes elapsed milliseconds into sink[key]."""
    start = time.perf_counter()
    try:
        yield
    finally:
        sink[key] = round((time.perf_counter() - start) * 1000, 1)


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct * (len(ordered) - 1))))
    return ordered[index]


class Telemetry:
    """Rolling query stats shared by every replica through the CacheStore."""

    def __init__(self, cache: CacheStore, window: int = WINDOW_SIZE) -> None:
        self._cache = cache
        self._window = window

    def record_query(self, timings: dict, abstained: bool, cache_hit: bool) -> None:
        sample = {
            "ts": round(time.time(), 3),
            "t": {k: v for k, v in (timings or {}).items() if k in _TIMING_KEYS},
            "a": bool(abstained),
            "c": bool(cache_hit),
        }
        # Best-effort: the CacheStore swallows backend errors, so a Redis
        # outage costs samples, never requests.
        self._cache.list_push_trim(
            TELEMETRY_KEY, json.dumps(sample), max_len=self._window, ttl_seconds=WINDOW_TTL
        )

    def rolling_stats(self) -> dict:
        raw = self._cache.list_range(TELEMETRY_KEY, self._window)
        samples: list[dict] = []
        for item in raw:
            try:
                samples.append(json.loads(item))
            except (TypeError, ValueError):
                continue  # a poisoned sample must not break the dashboard
        if not samples:
            return {"n": 0}

        stats: dict = {
            "n": len(samples),
            "abstention_rate": round(sum(s["a"] for s in samples) / len(samples), 3),
            "cache_hit_rate": round(sum(s["c"] for s in samples) / len(samples), 3),
            "window_start": min(s["ts"] for s in samples),
        }
        for key in _TIMING_KEYS:
            values = [s["t"][key] for s in samples if key in s.get("t", {})]
            if values:
                stats[key] = {
                    "p50": _percentile(values, 0.50),
                    "p95": _percentile(values, 0.95),
                }
        return stats
