"""Conversational session memory, backed by the CacheStore.

Redis-backed in production, so a follow-up question routed to a different
API replica still sees its history (the in-process dict this replaced made
conversation memory silently replica-affine). Sessions expire on a TTL
rather than an LRU cap, which is what a session actually is.
"""
import json
import logging

from core.interfaces import CacheStore

logger = logging.getLogger(__name__)

SESSION_KEY_PREFIX = "session:mem:"


class SessionMemory:
    def __init__(self, cache: CacheStore, max_turns: int = 5,
                 ttl_seconds: int = 24 * 3600) -> None:
        self._cache = cache
        self._max_turns = max_turns
        self._ttl = ttl_seconds

    @staticmethod
    def _key(session_id: str) -> str:
        return f"{SESSION_KEY_PREFIX}{session_id}"

    def get_history(self, session_id: str | None) -> list[dict[str, str]]:
        """Up to the last max_turns turns: [{'question': ..., 'answer': ...}]."""
        if not session_id:
            return []
        raw = self._cache.get(self._key(session_id))
        if not raw:
            return []
        try:
            history = json.loads(raw)
        except (TypeError, ValueError):
            # Corrupt payload degrades to "no history" — never 500s a query.
            logger.warning(f"Discarding unreadable session history for {session_id!r}.")
            return []
        return history if isinstance(history, list) else []

    def append_turn(self, session_id: str | None, question: str, answer: str) -> None:
        """Read-modify-write. Two concurrent turns in ONE session can drop a
        turn; sessions are sequential per user in practice, and losing a turn
        of context beats holding a distributed lock on the request path."""
        if not session_id:
            return
        history = self.get_history(session_id)
        history.append({"question": question, "answer": answer})
        self._cache.set(
            self._key(session_id),
            json.dumps(history[-self._max_turns:], ensure_ascii=False),
            ttl_seconds=self._ttl,  # sliding: an active session stays alive
        )

    def clear_session(self, session_id: str | None) -> None:
        if not session_id:
            return
        self._cache.delete(self._key(session_id))
