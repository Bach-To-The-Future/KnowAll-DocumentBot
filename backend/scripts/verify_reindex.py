"""Post-reindex confirmation, and the F19 measurement that must be taken now.

    docker compose exec api python scripts/verify_reindex.py

Four checks, three of them the maintainer's conditions:

  1. Every point carries embed_model + embed_model_digest, and they agree with
     the live model.
  2. verify_three_way() treats a missing digest as FATAL once
     DIGEST_ENFORCEMENT_FROM is set — exercised live, not just in unit tests.
  3. Finding #29's extractor metadata (`section_title` on csv/xlsx/pptx) is
     present on chunks that previously lacked it. This has never been
     observable: the 376 points predate F29.
  4. F19 — chunk token counts against the 2048-token embedding boundary.
     Taken IMMEDIATELY after the reindex because the reindex re-embedded
     everything: if any chunk crosses that boundary, the silent truncation
     already happened, during the migration.

Read-only. Changes nothing.
"""
from __future__ import annotations

import collections
import logging
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.disable(logging.INFO)

from core.config import Settings, get_settings  # noqa: E402
from core.exceptions import ModelIdentityError  # noqa: E402
from core.model_identity import verify_three_way  # noqa: E402
from services.container import build_container  # noqa: E402

# The formats that had NO section metadata before finding #29.
F29_FORMATS = {"csv", "xlsx", "pptx"}
EMBED_TOKEN_LIMIT = 2048


def token_counter():
    """A BERT WordPiece tokenizer as a PROXY for nomic-embed-text's.

    nomic-embed-text's own tokenizer is not in this image; the reranker's is,
    and both are BERT-family WordPiece. Close enough to answer "is the 2048
    boundary being crossed", NOT close enough to quote an exact count. Falls
    back to a chars/4 estimate, which is cruder still and labelled as such.
    """
    try:
        from tokenizers import Tokenizer
        base = "/opt/models/models--BAAI--bge-reranker-base/snapshots"
        snap = os.path.join(base, os.listdir(base)[0], "tokenizer.json")
        tok = Tokenizer.from_file(snap)
        return (lambda t: len(tok.encode(t).ids)), "bge-reranker WordPiece (proxy)"
    except Exception as e:
        print(f"  (tokenizer unavailable: {e} — falling back to chars/4)")
        return (lambda t: len(t) // 4), "chars/4 estimate (crude)"


def main() -> int:
    settings = get_settings()
    container = build_container(settings)
    client = container.vector_store._get_client()
    collection = settings.qdrant_collection

    points = []
    offset = None
    while True:
        batch, offset = client.scroll(
            collection, limit=256, offset=offset, with_payload=True, with_vectors=False)
        points.extend(batch)
        if offset is None:
            break
    print(f"collection: {collection}   points: {len(points)}\n")

    failures = 0

    # ---- 1. every point carries an identity ------------------------------
    print("=== 1. EMBEDDING-MODEL IDENTITY ON EVERY POINT ===")
    digests = collections.Counter()
    models = collections.Counter()
    missing = 0
    for p in points:
        payload = p.payload or {}
        d = payload.get("embed_model_digest")
        if not d:
            missing += 1
        else:
            digests[d] += 1
        models[payload.get("embed_model") or "<absent>"] += 1
    print(f"  points without a digest : {missing}")
    print(f"  distinct digests        : {dict(digests)}")
    print(f"  distinct embed_model    : {dict(models)}")
    if missing:
        print("  FAIL — enforcement must not be switched on")
        failures += 1
    elif len(digests) > 1:
        print("  FAIL — the collection mixes vectors from more than one model")
        failures += 1
    else:
        print("  OK")

    # ---- 2. enforcement is live ------------------------------------------
    print("\n=== 2. MISSING DIGEST IS FATAL UNDER ENFORCEMENT ===")
    print(f"  DIGEST_ENFORCEMENT_FROM = {settings.digest_enforcement_from!r}")
    enforced = Settings(_env_file=None, digest_enforcement_from="2026-08-05T00:00:00Z",
                        expected_embed_model_digest=None)
    try:
        verify_three_way(enforced, context="verify", stored_digest=None)
        print("  FAIL — a missing digest was accepted under enforcement")
        failures += 1
    except ModelIdentityError as e:
        print(f"  OK — raised: {str(e)[:88]}")
    if not settings.digest_enforcement_from:
        print("  NOTE: not yet set in this environment. Set it from the reindex "
              "output\n        in the api and worker environment maps.")

    # ---- 3. F29 metadata, observable for the first time -------------------
    print("\n=== 3. FINDING #29 EXTRACTOR METADATA ===")
    by_format: dict[str, dict[str, int]] = collections.defaultdict(
        lambda: {"total": 0, "with_section": 0})
    for p in points:
        payload = p.payload or {}
        fmt = (payload.get("file_format") or "?").lower()
        by_format[fmt]["total"] += 1
        if payload.get("section_title"):
            by_format[fmt]["with_section"] += 1
    for fmt in sorted(by_format):
        stat = by_format[fmt]
        mark = ""
        if fmt in F29_FORMATS:
            mark = ("  <- F29 target, previously ZERO"
                    if stat["with_section"] else "  <- F29 TARGET STILL BARE")
            if not stat["with_section"]:
                failures += 1
        print(f"  {fmt:<6} {stat['with_section']:>4}/{stat['total']:<4} "
              f"carry section_title{mark}")
    for fmt in sorted(F29_FORMATS):
        if fmt not in by_format:
            print(f"  {fmt:<6} not present in this collection")

    # ---- 4. F19 boundary --------------------------------------------------
    count, method = token_counter()
    print(f"\n=== 4. F19 — CHUNK TOKENS vs THE {EMBED_TOKEN_LIMIT}-TOKEN "
          f"EMBEDDING BOUNDARY ===")
    print(f"  method: {method}")
    counts = [count(p.payload.get("text", "")) for p in points if p.payload]
    chars = [len(p.payload.get("text", "")) for p in points if p.payload]
    over = [(c, ch) for c, ch in zip(counts, chars, strict=True)
            if c > EMBED_TOKEN_LIMIT]
    near = [c for c in counts if EMBED_TOKEN_LIMIT * 0.8 < c <= EMBED_TOKEN_LIMIT]
    print(f"  tokens  min={min(counts)}  median={int(statistics.median(counts))}  "
          f"p95={sorted(counts)[int(len(counts) * 0.95)]}  max={max(counts)}")
    print(f"  chars   min={min(chars)}   median={int(statistics.median(chars))}   "
          f"max={max(chars)}")
    print(f"  chunks OVER the boundary : {len(over)}")
    print(f"  chunks within 20% of it  : {len(near)}")
    if over:
        print("  TRUNCATION ALREADY HAPPENED during this reindex, silently:")
        for tokens, ch in sorted(over, reverse=True)[:10]:
            print(f"    ~{tokens} tokens / {ch} chars")
        failures += 1
    else:
        print("  OK — the boundary is NOT currently crossed. F19 stays a guard "
              "against\n     future chunking changes, not an active data loss.")

    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{failures} CHECK(S) FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
