"""Narrowing helpers for the SYNC redis client.

redis-py types every command as `ResponseT = Awaitable[Any] | Any`, because one
class serves both the sync and the async API. These stores construct the sync
client (`redis.Redis.from_url`), so the awaitable branch is unreachable at
runtime — but mypy cannot infer that from the constructor, and every call site
inherits the union. `json.loads(self._redis.get(k))` therefore fails
`arg-type`, and iterating an `mget` result fails `union-attr`.

WHY THIS RATHER THAN `# type: ignore`

An ignore suppresses the error and records nothing; it also silently keeps
suppressing after the underlying types change. These functions state the
assumption once, in one place, with the reason — and because they are ordinary
calls, a future reader can grep for them to find every site that depends on the
sync-client assumption.

If these stores ever gain an async client, the assumption breaks and these are
the call sites to revisit.
"""
from __future__ import annotations

from typing import Any, cast


def as_text(value: Any) -> str | None:
    """A string-valued reply (GET, or one element of MGET), or None if absent.

    `decode_responses=True` is set at construction, so replies arrive as `str`
    rather than `bytes`.
    """
    return cast("str | None", value)


def as_int(value: Any) -> int:
    """An integer reply (INCR, TTL). Redis returns these as integers already;
    the `int()` is what makes the narrowing checkable rather than asserted."""
    return int(cast("int", value))


def as_list(value: Any) -> list[Any]:
    """A list reply (MGET, LRANGE, pipeline EXECUTE)."""
    return cast("list[Any]", value)
