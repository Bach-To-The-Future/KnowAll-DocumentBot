"""Findings #19 and #3, merged: one token-counting utility, both boundaries.

They were filed separately and are the same problem — a budget nothing counts
against — with opposite correct responses:

    EMBEDDING, 2048 tokens      FAIL LOUD. A truncated embedding is a WRONG
                                VECTOR: Ollama returns HTTP 200 with a
                                well-formed 768-dim result computed from part
                                of the text. Nothing downstream can tell. There
                                is no graceful degradation available, because
                                the damage is already in the index.

    CONTEXT, 8192 tokens        DEGRADE GRACEFULLY, dropping the LOWEST-RANKED
                                chunks first. Over-budget context is silently
                                truncated from the FRONT, which is where the
                                system prompt's grounding rules live — the
                                model loses rule 3 and keeps the passages.
                                Answering with fewer chunks beats answering
                                with no instructions.

MEASURED HEADROOM (2026-08-06, this corpus, these settings). NEITHER BOUNDARY
IS REACHABLE TODAY:

    stored chunk       max ~1056 tokens  against 2048   (verify_reindex.py)
    assembled prompt   max  5375 tokens  against 8192   (prompt_distribution.py)

That makes this a **pure regression guard**, not an active rescue — and more
valuable for it, not less. Nothing else in the system would notice if a config
change made either boundary reachable, and **both failure modes are silent**.

WHY THE NOMINAL BUDGETS UNDERSTATE REAL SIZE BY ~2x — the stacking relationship
that any future violation will come from:

    chunk_size = 550 chars          nominal
    table_chunk_char_budget = 1600  nominal
    largest observed stored chunk   2991 chars

Section-title prefixes and table row-groups stack on top of the nominal budget.
So a chunk budget of N does not produce chunks of N. Every error message below
carries this, because a violation is only interpretable with it.
"""
from __future__ import annotations

import logging
import os
from typing import Protocol

logger = logging.getLogger(__name__)

EMBED_TOKEN_LIMIT = 2048
CONTEXT_TOKEN_LIMIT = 8192

# Measured 2026-08-06; quoted in error messages so a violation is interpretable.
MEASURED_MAX_STORED_TOKENS = 1056
MEASURED_MAX_PROMPT_TOKENS = 5375
MEASURED_MAX_STORED_CHARS = 2991
NOMINAL_CHUNK_CHARS = 550
NOMINAL_TABLE_CHARS = 1600

_STACKING_NOTE = (
    f"Nominal chunk budgets understate real size by roughly 2x: chunk_size="
    f"{NOMINAL_CHUNK_CHARS} chars and table_chunk_char_budget="
    f"{NOMINAL_TABLE_CHARS} chars have produced stored chunks of "
    f"{MEASURED_MAX_STORED_CHARS} chars, because section prefixes and table "
    f"row-groups stack on top of the nominal budget."
)


class _Counter(Protocol):
    def __call__(self, text: str) -> int: ...


def _load_counter() -> tuple[_Counter, str]:
    """A BERT WordPiece tokenizer as a PROXY for nomic-embed-text's.

    nomic-embed-text's own tokenizer is not in the image; the reranker's is,
    and both are BERT-family WordPiece. Good enough to place text against a
    limit; NOT good enough to quote an exact count, and callers must not.
    """
    try:
        from tokenizers import Tokenizer

        base = "/opt/models/models--BAAI--bge-reranker-base/snapshots"
        snapshot = os.path.join(base, os.listdir(base)[0], "tokenizer.json")
        tokenizer = Tokenizer.from_file(snapshot)
        return (lambda text: len(tokenizer.encode(text).ids)), "wordpiece-proxy"
    except Exception as e:  # pragma: no cover - environment dependent
        logger.warning(
            f"Token counting falling back to a chars/4 estimate ({e}). Budget "
            f"checks still fire, but the counts are crude."
        )
        return (lambda text: len(text) // 4), "chars/4-estimate"


_counter: _Counter | None = None
_method = "uninitialised"


def count_tokens(text: str) -> int:
    global _counter, _method
    if _counter is None:
        _counter, _method = _load_counter()
    return _counter(text)


def counting_method() -> str:
    if _counter is None:
        count_tokens("")
    return _method


class EmbeddingBudgetExceeded(ValueError):
    """Raised instead of embedding text that would be silently truncated."""


def check_embedding_budget(text: str, *, source: str) -> int:
    """FAIL LOUD. Returns the token count; raises if it exceeds the budget.

    No graceful path exists: Ollama truncates at 2048 and returns HTTP 200 with
    a valid-looking 768-dim vector computed from a prefix of the text. The
    vector is wrong, the index accepts it, and every later retrieval is
    silently degraded.
    """
    tokens = count_tokens(text)
    if tokens <= EMBED_TOKEN_LIMIT:
        return tokens
    raise EmbeddingBudgetExceeded(
        f"'{source}' is ~{tokens} tokens, over the {EMBED_TOKEN_LIMIT}-token "
        f"embedding limit ({counting_method()}). Ollama would truncate it and "
        f"return HTTP 200 with a well-formed vector computed from only part of "
        f"the text — a WRONG vector that nothing downstream can detect. "
        f"Measured headroom before this change: the largest stored chunk was "
        f"~{MEASURED_MAX_STORED_TOKENS} tokens, so the boundary was not "
        f"reachable; something has grown chunks by ~"
        f"{tokens / MEASURED_MAX_STORED_TOKENS:.1f}x. {_STACKING_NOTE}"
    )


def fit_context_budget(
    system_prompt: str, question: str, chunk_texts: list[str],
    *, limit: int = CONTEXT_TOKEN_LIMIT,
) -> tuple[list[str], int, int]:
    """DEGRADE GRACEFULLY. Returns (kept_texts, kept_tokens, dropped_count).

    `chunk_texts` must be in RANK ORDER, best first. Chunks are dropped from
    the END — the lowest-ranked — because over-budget context is truncated by
    the runtime from the FRONT, where the system prompt's grounding rules sit.
    Losing rule 3 while keeping every passage is the worst possible trade, and
    it is what happens if nothing counts.

    At least one chunk is always kept: answering from the best passage alone
    beats abstaining because the budget was tight.
    """
    overhead = count_tokens(system_prompt) + count_tokens(question)
    kept: list[str] = []
    total = overhead
    for index, text in enumerate(chunk_texts):
        tokens = count_tokens(text)
        if index > 0 and total + tokens > limit:
            break
        kept.append(text)
        total += tokens

    dropped = len(chunk_texts) - len(kept)
    if dropped:
        logger.warning(
            f"Context budget: dropped {dropped} of {len(chunk_texts)} chunks "
            f"(lowest-ranked first) to fit ~{total} tokens under {limit} "
            f"({counting_method()}). Measured headroom before this change: the "
            f"largest assembled prompt was ~{MEASURED_MAX_PROMPT_TOKENS} tokens "
            f"against {CONTEXT_TOKEN_LIMIT}, so the boundary was not reachable. "
            f"{_STACKING_NOTE}"
        )
    return kept, total, dropped
