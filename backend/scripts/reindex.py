"""Phase 2.1 reindex — ONE pass that does all three jobs.

    docker compose exec api python scripts/reindex.py --confirm

Three things needed writing into every point, and doing them as three separate
reindexes would mean three full re-embeddings of the corpus and three windows
in which the collection is half-migrated:

  1. `embed_model` + `embed_model_digest` on every payload (finding #2 / 2.1).
     Without them a republished tag leaves a collection silently mixing vectors
     from two models, and nothing downstream can tell.
  2. `digest_enforcement_from`, which turns "this point has no digest" from
     "unknown" into "this point escaped the reindex". Until that marker exists,
     the ambiguity is permanent.
  3. Finding #29's extractor metadata (`section_title` on csv/xlsx/pptx), which
     every existing point predates.

So: one pass.

WHY THE BASELINES EITHER SIDE ARE INCOMPARABLE
Re-extraction re-chunks, and the reindex re-embeds. `eval/compare.py` will
refuse to diff a pre- and post-reindex baseline on its own — `embed_model_digest`
is a HARD field — and that refusal is correct, not an obstacle. Record a fresh
baseline after this runs; do not attempt to compare it to an older one.

SAFETY
  * Refuses without --confirm. This rewrites every point in the collection.
  * Fails closed on embedding-model identity BEFORE touching anything: a
    reindex under a drifted model would bake the drift in permanently.
  * Idempotent. Point IDs are uuid5(source:etag:chunk_seq) and the etag comes
    from object storage, so re-running overwrites in place rather than
    duplicating. The staged swap removes any point whose etag moved.
  * VERIFIES the outcome rather than assuming it: after the pass it scrolls the
    whole collection and fails if a single point lacks a digest. A reindex that
    reports success while leaving points behind is exactly the class of green
    checkmark this project keeps finding.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from datetime import UTC, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import get_settings  # noqa: E402
from core.model_identity import verify_embedding_model  # noqa: E402
from services.container import build_container  # noqa: E402


def verify_every_point_has_a_digest(container, expected: str | None) -> list[str]:
    """Scroll the whole collection. Returns a list of problems, empty if clean."""
    client = container.vector_store._get_client()
    collection = container.settings.qdrant_collection
    problems: list[str] = []
    missing = 0
    mismatched: dict[str, int] = {}
    total = 0
    offset = None
    while True:
        points, offset = client.scroll(
            collection, limit=256, offset=offset,
            with_payload=["embed_model_digest", "source"], with_vectors=False,
        )
        for point in points:
            total += 1
            digest = (point.payload or {}).get("embed_model_digest")
            if not digest:
                missing += 1
            elif expected and digest != expected:
                mismatched[digest] = mismatched.get(digest, 0) + 1
        if offset is None:
            break

    if missing:
        problems.append(f"{missing} of {total} points carry NO embed_model_digest")
    if mismatched:
        problems.append(
            f"{sum(mismatched.values())} of {total} points carry a digest other than "
            f"{expected}: {mismatched}"
        )
    print(f"verified {total} points in {collection}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", action="store_true",
                        help="required: this rewrites every point in the collection")
    parser.add_argument("--dry-run", action="store_true",
                        help="list what would be reindexed, touch nothing")
    args = parser.parse_args()

    settings = get_settings()
    container = build_container(settings)

    # Fail closed BEFORE touching anything. A reindex under a drifted model
    # would bake the drift into every vector, permanently and invisibly.
    digest = verify_embedding_model(settings, context="reindex")
    if digest is None:
        print("REFUSING: the embedding model's digest could not be determined.\n"
              "  Reindexing under an unidentifiable model produces a collection\n"
              "  whose vectors cannot be attributed to anything.", file=sys.stderr)
        return 2

    # The set to reindex is what the COLLECTION contains, not what the bucket
    # contains. Enumerating the bucket looked equivalent and is not: this
    # deployment's bucket held 7 objects with no vectors (backpressure test
    # fixtures and a deliberately broken file), so a bucket-driven reindex would
    # have quietly ADDED content to the corpus while claiming to rewrite it.
    # A reindex must not change corpus membership.
    client = container.vector_store._get_client()
    points, _ = client.scroll(settings.qdrant_collection, limit=100_000,
                              with_payload=["source"], with_vectors=False)
    in_collection = {(p.payload or {}).get("source") for p in points}
    in_collection.discard(None)
    in_bucket = set(container.storage.list_keys())

    keys = sorted(in_collection & in_bucket)
    unbacked = sorted(in_collection - in_bucket)
    extra = sorted(in_bucket - in_collection)

    print(f"collection      : {settings.qdrant_collection}")
    print(f"bucket          : {container.storage.bucket}")
    print(f"sources indexed : {len(in_collection)}")
    print(f"to reindex      : {len(keys)}")
    print(f"embed model     : {settings.embed_model} @ {digest}")

    if extra:
        print(f"\nSKIPPING {len(extra)} object(s) present in the bucket but NOT in "
              f"the collection.\n  Reindexing them would ADD content, which is a "
              f"corpus change, not a migration:")
        for key in extra:
            print(f"    {key}")
        print("  Ingest them deliberately through the normal path if they belong.")

    if unbacked:
        # Fatal, and worth saying BEFORE a long run rather than after: these
        # points can never receive a digest, so the final scroll will fail and
        # enforcement can never be switched on.
        print(f"\nBLOCKED: {len(unbacked)} source(s) are indexed but have no object "
              f"in the bucket:", file=sys.stderr)
        for source in unbacked:
            print(f"    {source}", file=sys.stderr)
        print("  Their points cannot be rewritten, so they would remain without a\n"
              "  digest and DIGEST_ENFORCEMENT_FROM could never be set. Delete them\n"
              "  from the collection or restore the objects first.", file=sys.stderr)
        return 2

    if args.dry_run:
        print()
        for key in keys:
            print(f"  would reindex {key}")
        return 0
    if not args.confirm:
        print("REFUSING without --confirm: this rewrites every point.", file=sys.stderr)
        return 2
    if not keys:
        print("Nothing to reindex — object storage is empty.", file=sys.stderr)
        return 2

    container.vector_store.ensure_ready()
    started = datetime.now(UTC).isoformat()
    total_chunks = 0
    failures: list[tuple[str, str]] = []

    for key in keys:
        tmp_dir = tempfile.mkdtemp(prefix="knowall_reindex_")
        local = os.path.join(tmp_dir, os.path.basename(key.replace("\\", "/")))
        try:
            etag = container.storage.head_etag(container.storage.bucket, key)
            container.storage.download_file(container.storage.bucket, key, local)
            count = container.ingestion.process_document(local, etag=etag)
            total_chunks += count
            print(f"  {key:<44} {count:>5} chunks")
        except Exception as e:  # one bad document must not abort the migration
            failures.append((key, str(e)))
            print(f"  {key:<44}  FAILED: {e}", file=sys.stderr)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"\n{total_chunks} chunks reindexed from "
          f"{len(keys) - len(failures)}/{len(keys)} documents.")

    problems = verify_every_point_has_a_digest(container, digest)
    if failures:
        problems.append(f"{len(failures)} document(s) failed: "
                        f"{[k for k, _ in failures]}")

    if problems:
        print("\nREINDEX INCOMPLETE — do NOT set DIGEST_ENFORCEMENT_FROM:",
              file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("\nEnforcement would turn every missed point into a hard failure at "
              "query time.", file=sys.stderr)
        return 1

    print("\nEvery point carries the expected digest. Enforcement can be turned on:")
    print(f"\n    DIGEST_ENFORCEMENT_FROM={started}\n")
    print("Set that in the api and worker environment. From then on a point with "
          "no digest is a point that escaped the reindex, not an unknown one.")
    print("\nRecord a FRESH baseline. Pre- and post-reindex baselines are "
          "INCOMPARABLE by construction (embed_model_digest is a hard field) and "
          "eval/compare.py will refuse to diff them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
