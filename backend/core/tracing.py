"""Phase 4.2 — one trace id, browser to worker log.

A document that fails extraction could not be traced back to the upload that
triggered it: `trace_id` was generated server-side per query and never
propagated in either direction. The ingestion path is where that hurts most,
because ingestion is asynchronous — by the time it fails, the request that
started it is long gone.

    browser  →  X-Trace-Id header
    proxy    →  forwards the header unchanged
    API      →  adopts it, or mints one; echoes it back on the response
    worker   →  receives it as a job argument, logs it on every line
    DLQ      →  stores it, so a dead-lettered document is not an orphan

NOT AN IDENTITY. A browser-supplied trace id is attacker-controlled: it can be
forged, repeated, or set to another user's value. It is a CORRELATION AID and
nothing else — never an authorisation input, never a cache key, never a
partition key. It is sanitised on arrival so it cannot smuggle anything into a
log line or a JSON field.
"""
from __future__ import annotations

import re
import uuid

TRACE_HEADER = "X-Trace-Id"

# Hex-ish, bounded. Anything else is replaced rather than rejected: a malformed
# trace id must not fail a request whose only problem is a debugging header.
_SAFE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def new_trace_id() -> str:
    return uuid.uuid4().hex[:12]


def adopt_trace_id(supplied: str | None) -> str:
    """Take the caller's trace id if it is safe, otherwise mint one.

    Sanitising rather than trusting: the value lands in structured log lines
    and in the DLQ payload, so an unbounded or newline-bearing string could
    forge log entries or bloat a Redis record.
    """
    if supplied and _SAFE.match(supplied):
        return supplied
    return new_trace_id()
