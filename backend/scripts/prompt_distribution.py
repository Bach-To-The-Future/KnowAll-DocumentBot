"""Post-C3 assembled-prompt token DISTRIBUTION, on real retrieval.

    docker compose exec api python scripts/prompt_distribution.py

Feeds three decisions, which is why it is the distribution and not the ceiling:

  1. THE TRUNCATION GUARD (F19/#3). Where the tail actually sits against the
     8192-token context budget, and the 2048-token embedding budget.
  2. THE LATENCY CURVE. Prompt size is the input to prefill, which dominates
     CPU generation — 48s warm at ~7,700 tokens.
  3. IS parent_char_budget=4000 x rerank_top_n=5 OVER-PROVISIONED?
       median far below the ceiling  -> only the tail needs bounding
       median near the ceiling       -> the budget is systematically oversized,
                                        and reducing it is a latency lever that
                                        trades against retrieval quality, which
                                        only eval can settle

Uses `QueryService.build_prompt` over real retrieved chunks, not synthetic
text — the D6 lesson: a constructed fixture measures what its author believed.
"""
from __future__ import annotations

import json
import logging
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.disable(logging.INFO)

from core.config import get_settings  # noqa: E402
from services.container import build_container  # noqa: E402
from services.query import SYSTEM_PROMPT  # noqa: E402

EMBED_LIMIT = 2048
CONTEXT_LIMIT = 8192


def token_counter():
    """Same BERT WordPiece proxy scripts/verify_reindex.py uses, and the same
    caveat: good enough to place a distribution against a limit, not good
    enough to quote an exact count."""
    try:
        from tokenizers import Tokenizer
        base = "/opt/models/models--BAAI--bge-reranker-base/snapshots"
        snap = os.path.join(base, os.listdir(base)[0], "tokenizer.json")
        tok = Tokenizer.from_file(snap)
        return (lambda t: len(tok.encode(t).ids)), "bge-reranker WordPiece (proxy)"
    except Exception as e:
        print(f"  (tokenizer unavailable: {e}; falling back to chars/4)")
        return (lambda t: len(t) // 4), "chars/4 (crude)"


def pct(values: list[int], p: float) -> int:
    return sorted(values)[min(int(len(values) * p), len(values) - 1)]


def main() -> int:
    settings = get_settings()
    container = build_container(settings)
    count, method = token_counter()

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    golden = json.load(open(os.path.join(here, "eval", "golden_set.json"),
                            encoding="utf-8"))["entries"]
    questions = [e["question"] for e in golden]

    print(f"collection : {settings.qdrant_collection}")
    print(f"knobs      : rerank_top_n={settings.rerank_top_n}  "
          f"parent_char_budget={settings.parent_char_budget}  "
          f"context_mode={settings.retrieval_context_mode}")
    print(f"budgets    : embedding {EMBED_LIMIT}  context {CONTEXT_LIMIT}")
    print(f"method     : {method}\n")

    prompt_tokens: list[int] = []
    chunk_tokens: list[int] = []
    returned: list[int] = []
    system_tokens = count(SYSTEM_PROMPT)

    for q in questions:
        chunks = container.retrieval.retrieve(q, filters=None,
                                              k=settings.rerank_top_n)
        returned.append(len(chunks))
        for c in chunks:
            chunk_tokens.append(count(c.text))
        if not chunks:
            continue
        prompt = container.query.build_prompt(q, chunks)
        prompt_tokens.append(count(prompt) + system_tokens)

    if not prompt_tokens:
        print("No prompts assembled — is the collection populated?", file=sys.stderr)
        return 1

    print(f"=== ASSEMBLED PROMPT (system + context + question), n={len(prompt_tokens)} ===")
    print(f"  min={min(prompt_tokens)}  p25={pct(prompt_tokens, .25)}  "
          f"MEDIAN={int(statistics.median(prompt_tokens))}  "
          f"p75={pct(prompt_tokens, .75)}  p95={pct(prompt_tokens, .95)}  "
          f"max={max(prompt_tokens)}")
    over = [t for t in prompt_tokens if t > CONTEXT_LIMIT]
    near = [t for t in prompt_tokens if CONTEXT_LIMIT * 0.8 < t <= CONTEXT_LIMIT]
    print(f"  over {CONTEXT_LIMIT}: {len(over)}   within 20% of it: {len(near)}")
    print(f"  median as % of the context budget: "
          f"{100 * statistics.median(prompt_tokens) / CONTEXT_LIMIT:.0f}%")

    # CAREFUL: these are chunks AFTER context expansion, which is what enters
    # the prompt. The 2048-token EMBEDDING budget does NOT apply to them — it
    # applies to the chunk as STORED, before expansion, and expanded text is
    # never re-embedded. Reporting a breach here would be a measurement error.
    # scripts/verify_reindex.py measures the stored text, which is the correct
    # reference for F19 (max ~1056 tokens on the production collection).
    print(f"\n=== PER-CHUNK AFTER EXPANSION (prompt contribution), n={len(chunk_tokens)} ===")
    if chunk_tokens:
        print(f"  min={min(chunk_tokens)}  MEDIAN={int(statistics.median(chunk_tokens))}  "
              f"p95={pct(chunk_tokens, .95)}  max={max(chunk_tokens)}")
        big = len([t for t in chunk_tokens if t > EMBED_LIMIT])
        print(f"  larger than the {EMBED_LIMIT}-token EMBEDDING budget: {big}")
        print("  ^ NOT an F19 breach: expansion happens after retrieval and this")
        print("    text is never re-embedded. It shows what parent_char_budget adds.")

    print(f"\n=== CHUNKS RETURNED per query (rerank_top_n={settings.rerank_top_n}) ===")
    print(f"  min={min(returned)}  median={int(statistics.median(returned))}  "
          f"max={max(returned)}  zero-result queries={returned.count(0)}")

    print("\n=== READING ===")
    median = statistics.median(prompt_tokens)
    ratio = median / CONTEXT_LIMIT
    if ratio > 0.7:
        print(f"  MEDIAN is {ratio:.0%} of the context budget. parent_char_budget x")
        print("  rerank_top_n is SYSTEMATICALLY oversized for this generator, and")
        print("  reducing it is a latency lever. It trades against retrieval")
        print("  quality, which only eval can settle -- do not tune it here.")
    elif ratio < 0.35:
        print(f"  MEDIAN is only {ratio:.0%} of the budget; the ceiling is a TAIL")
        print("  phenomenon. Bound the tail rather than shrinking the budget --")
        print("  shrinking it would cost retrieval quality on the common case for")
        print("  no latency benefit there.")
    else:
        print(f"  MEDIAN is {ratio:.0%} of the budget. Neither clearly oversized nor")
        print("  purely a tail problem; the guard should degrade gracefully rather")
        print("  than the budget being re-cut.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
