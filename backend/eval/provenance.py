"""Provenance tuple: what a baseline's numbers are actually a measurement OF.

An eval number is meaningless without the conditions that produced it. Every
baseline records this tuple, and compare.py uses it to decide whether two
baselines may be diffed at all.

Field classes — deliberately small and explicit:

  HARD      differ => INCOMPARABLE (hard refusal, no metrics printed).
            These change what the vectors MEAN or what is being measured, so
            the numbers are not on the same scale:
              corpus_manifest_sha256, embed_model, embed_model_digest,
              chunk_size, chunk_overlap, table_chunk_char_budget,
              table_max_rows_per_chunk, eval_mode,
              n_answerable, n_unanswerable
            eval_mode is hard because retrieval-mode numbers (deterministic,
            no LLM) and full-mode numbers (rewrite + expansion in the loop)
            are not comparable quantities.

            n_answerable / n_unanswerable are the SIZE OF THE DENOMINATOR each
            rate is computed over. They are hard because a rate compared across
            two populations is not a comparison at all.

            WHY THEY EXIST. The 2026-08-10 audit compared COMPARABLE, exit 0,
            with hit_at_k 0.682 -> 0.867 (+0.185) and mrr_at_k likewise — while
            n_answerable fell 22 -> 15, because seven history-bearing
            conversational entries had been retagged full-mode-only and are
            skipped in retrieval mode. Those are plausibly the HARDER retrieval
            cases, so removing them raised hit_at_k mechanically. The comparator
            reported "no metric regressed" over a denominator that had changed
            by a third.

            That was the THIRD instance of one class in this engagement — a
            metric improving because its population got easier, not because the
            system did. See docs/HANDOFF.md section 1d.

  SEMANTIC  differ => COMPARABLE_WITH_SEMANTIC_DRIFT. Same scale, but these
            change WHAT GETS RETRIEVED, so a delta must not be attributed to
            the change under test without saying so:
              retrieval_fetch_k, rerank_top_n, rerank_score_floor,
              retrieval_context_mode, neighbor_window, parent_char_budget,
              enable_multi_query, query_expansion_count, enable_answer_cache,
              reranker_model

  COSMETIC  differ => COMPARABLE_WITH_COSMETIC_DRIFT. Recorded for forensics;
            no expected effect on retrieval:
              git_sha, api_image_digest, web_image_digest,
              reranker_revision, bm25_revision

  llm_model is CONDITIONAL — see classify_fields(). In full mode a different
  generation model rewrites and expands queries differently, which changes
  retrieval INPUTS; that is a different system, not drift, so it is HARD. In
  retrieval mode the LLM is out of the loop entirely and it is cosmetic.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from datetime import UTC, datetime
from typing import Any

from core.config import Settings

RETRIEVAL_MODE = "retrieval"
FULL_MODE = "full"

_HARD_BASE = (
    "corpus_manifest_sha256",
    "embed_model",
    "embed_model_digest",
    "chunk_size",
    "chunk_overlap",
    "table_chunk_char_budget",
    "table_max_rows_per_chunk",
    "eval_mode",
    # The denominators. A rate compared across two populations is not a
    # comparison — see the module docstring.
    "n_answerable",
    "n_unanswerable",
)

_SEMANTIC_BASE = (
    "reranker_model",
    "retrieval_fetch_k",
    "rerank_top_n",
    "rerank_score_floor",
    "abstention_score_floor",
    "contain_untrusted_passages",
    "retrieval_context_mode",
    "neighbor_window",
    "parent_char_budget",
    "enable_multi_query",
    "query_expansion_count",
    "enable_answer_cache",
)

_COSMETIC_BASE = (
    "reranker_revision",
    "bm25_revision",
    "git_sha",
    "api_image_digest",
    "web_image_digest",
)


def classify_fields(eval_mode: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """(hard, semantic, cosmetic) for the given mode.

    `llm_model` moves between classes: hard in full mode (it drives rewrite and
    expansion, therefore retrieval inputs), cosmetic in retrieval mode (the LLM
    never runs).
    """
    if eval_mode == FULL_MODE:
        return (*_HARD_BASE, "llm_model"), _SEMANTIC_BASE, _COSMETIC_BASE
    return _HARD_BASE, _SEMANTIC_BASE, (*_COSMETIC_BASE, "llm_model")


def _git_sha() -> str:
    """The env var comes FIRST and is the only path that works in the container.

    The image build context is `backend/`, so there is no `.git` inside the
    container and `git rev-parse` can never succeed there — every in-container
    baseline recorded "unknown" until this was fixed. Pass it at the call site:

        docker compose exec -e KNOWALL_GIT_SHA=$(git rev-parse HEAD) api \\
            python eval/run_eval.py ...

    The subprocess fallback is for host-side runs. Still "unknown" when neither
    works — an honest gap, not a fabricated value.
    """
    from_env = os.getenv("KNOWALL_GIT_SHA", "").strip()
    if from_env:
        return from_env
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def build(
    settings: Settings,
    *,
    corpus_manifest_sha256: str,
    embed_model_digest: str | None,
    eval_mode: str,
    n_answerable: int,
    n_unanswerable: int,
) -> dict[str, Any]:
    """Assemble the tuple. Model revisions come from env baked into the image
    at build time (see api/Dockerfile), so they describe the container actually
    running rather than the host's opinion of it.

    `n_answerable` / `n_unanswerable` are REQUIRED rather than defaulted: a
    baseline recorded without them would compare as though the population had
    never changed, which is the exact defect they exist to catch.
    """
    return {
        "corpus_manifest_sha256": corpus_manifest_sha256,
        "n_answerable": n_answerable,
        "n_unanswerable": n_unanswerable,
        "embed_model": settings.embed_model,
        "embed_model_digest": embed_model_digest or "unpinned",
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "table_chunk_char_budget": settings.table_chunk_char_budget,
        "table_max_rows_per_chunk": settings.table_max_rows_per_chunk,
        "eval_mode": eval_mode,
        "reranker_model": settings.reranker_model,
        "retrieval_fetch_k": settings.retrieval_fetch_k,
        "rerank_top_n": settings.rerank_top_n,
        "rerank_score_floor": settings.rerank_score_floor,
        "abstention_score_floor": settings.abstention_score_floor,
        "contain_untrusted_passages": settings.contain_untrusted_passages,
        "retrieval_context_mode": settings.retrieval_context_mode,
        "neighbor_window": settings.neighbor_window,
        "parent_char_budget": settings.parent_char_budget,
        "enable_multi_query": settings.enable_multi_query,
        "query_expansion_count": settings.query_expansion_count,
        "enable_answer_cache": settings.enable_answer_cache,
        "llm_model": settings.llm_model,
        "reranker_revision": os.getenv("KNOWALL_RERANKER_REVISION") or "unpinned",
        "bm25_revision": os.getenv("KNOWALL_BM25_REVISION") or "unpinned",
        "git_sha": _git_sha(),
        # Also passed in at the call site — a container cannot see its own
        # image ID without the docker socket, and mounting that to record a
        # provenance field would be a poor trade.
        "api_image_digest": os.getenv("KNOWALL_API_IMAGE_ID", "unknown"),
        "web_image_digest": os.getenv("KNOWALL_WEB_IMAGE_ID", "unknown"),
        # informational only, never compared
        "recorded_at": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
    }


def fingerprint(tuple_: dict[str, Any]) -> str:
    """Stable hash over the HARD fields — the identity of the measurement
    conditions. Same fingerprint => the numbers are on the same scale."""
    hard, _, _ = classify_fields(str(tuple_.get("eval_mode", RETRIEVAL_MODE)))
    payload = {k: tuple_.get(k) for k in hard}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
