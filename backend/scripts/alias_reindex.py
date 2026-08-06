"""Phase 4.1 — zero-downtime reindex via an atomic alias swap.

    python scripts/alias_reindex.py --dry-run
    python scripts/alias_reindex.py --confirm

Every future embedding-model or chunking change depends on this. The in-place
`scripts/reindex.py` rewrites the live collection: correct, but it degrades
retrieval for the whole run and has no way back except the snapshot.

    build   index into a NEW collection under a versioned name
    verify  dimension, count, digests, payload indexes — BEFORE anything moves
    swap    point the alias at the new collection, atomically
    drop    remove the old collection only after the swap succeeds

TWO LESSONS FROM THE IN-PLACE SCRIPT, carried forward deliberately:

  1. ENUMERATE FROM THE SOURCE OF TRUTH. `reindex.py` first enumerated the
     BUCKET, which held 20 objects against the collection's 13 sources — seven
     were test fixtures never successfully indexed. A bucket-driven rebuild
     would have quietly ADDED content while reporting a migration. Membership
     comes from the live collection; the bucket only supplies bytes.

  2. THE ENFORCEMENT MARKER IS PRINTED ONLY AFTER A FULL SCROLL confirms every
     point carries a digest. A partial run must not be able to switch
     enforcement on against a half-migrated collection.

VERIFICATION FORCES THE FAILURE. `--self-test` builds a collection with a
deliberately wrong vector dimension and confirms the swap is refused BEFORE the
alias moves — because a verification that has only ever seen the happy path is
indistinguishable from no verification.
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import tempfile
from datetime import UTC, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.disable(logging.INFO)

from qdrant_client.http import models as qm  # noqa: E402

from core.config import get_settings  # noqa: E402
from core.model_identity import verify_embedding_model  # noqa: E402
from integrations.qdrant_store import REQUIRED_PAYLOAD_INDEXES  # noqa: E402
from services.container import build_container  # noqa: E402


class VerificationFailed(RuntimeError):
    """Raised before the alias moves. The live collection is untouched."""


def resolve_target(client, alias: str) -> str | None:
    """Which collection the alias currently points at, if any."""
    try:
        for entry in client.get_aliases().aliases:
            if entry.alias_name == alias:
                return str(entry.collection_name)
    except Exception:
        pass
    return None


def verify_candidate(client, candidate: str, *, expect_points: int,
                     expect_dim: int, expect_digest: str) -> None:
    """Everything that must hold BEFORE the alias moves.

    Ordered cheapest-first so an obvious failure does not pay for a full
    scroll, but every check runs against the live candidate rather than
    against what the build reported doing.
    """
    info = client.get_collection(candidate)

    vectors = info.config.params.vectors
    dim = vectors.size if hasattr(vectors, "size") else list(vectors.values())[0].size
    if dim != expect_dim:
        raise VerificationFailed(
            f"vector dimension is {dim}, expected {expect_dim}. Swapping the "
            f"alias would point every query at vectors of the wrong shape."
        )

    count = client.count(candidate).count
    if count != expect_points:
        raise VerificationFailed(
            f"{count} points, expected {expect_points}. A short build means "
            f"documents were lost; a long one means content was added."
        )

    present = set((info.payload_schema or {}).keys())
    missing = [n for n, _ in REQUIRED_PAYLOAD_INDEXES if n not in present]
    if missing:
        raise VerificationFailed(
            f"payload indexes missing: {missing}. Filtered retrieval would "
            f"full-scan (phase 2.6)."
        )

    # Full scroll, last: this is the check that licenses the enforcement marker.
    offset, seen, without = None, 0, 0
    digests: set[str] = set()
    while True:
        points, offset = client.scroll(
            candidate, limit=256, offset=offset,
            with_payload=["embed_model_digest"], with_vectors=False)
        for point in points:
            seen += 1
            digest = (point.payload or {}).get("embed_model_digest")
            if digest:
                digests.add(str(digest))
            else:
                without += 1
        if offset is None:
            break
    if without:
        raise VerificationFailed(
            f"{without} of {seen} points carry no embed_model_digest.")
    if digests != {expect_digest}:
        raise VerificationFailed(
            f"collection holds digests {digests}, expected exactly "
            f"{{{expect_digest}}} — it mixes vectors from more than one model.")


def build_candidate(container, settings, keys: list[str], candidate: str,
                    etag_of) -> int:
    """Index into `candidate`. Returns the chunk count."""
    original = container.vector_store._collection
    container.vector_store._collection = candidate
    try:
        container.vector_store.ensure_ready()
        total = 0
        for key in keys:
            tmp = tempfile.mkdtemp(prefix="knowall_alias_")
            local = os.path.join(tmp, os.path.basename(key.replace("\\", "/")))
            try:
                container.storage.download_file(container.storage.bucket, key, local)
                count = container.ingestion.process_document(local, etag=etag_of(key))
                total += count
                print(f"    {key:<44} {count:>5} chunks")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        return total
    finally:
        container.vector_store._collection = original


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-test", action="store_true",
                        help="force a wrong-dimension candidate and prove the "
                             "swap is refused before the alias moves")
    parser.add_argument("--keep-old", action="store_true",
                        help="do not drop the previous collection after the swap")
    args = parser.parse_args()

    settings = get_settings()
    container = build_container(settings)
    client = container.vector_store._get_client()
    alias = settings.qdrant_collection

    digest = verify_embedding_model(settings, context="alias reindex")
    if digest is None:
        print("REFUSING: the embedding model's digest could not be determined.",
              file=sys.stderr)
        return 2

    current = resolve_target(client, alias) or alias
    if args.self_test:
        return self_test(client, alias, current, settings)

    # LESSON 1: membership from the live collection, bytes from the bucket.
    points, _ = client.scroll(current, limit=100_000,
                              with_payload=["source"], with_vectors=False)
    in_collection = {(p.payload or {}).get("source") for p in points}
    in_collection.discard(None)
    in_bucket = set(container.storage.list_keys())
    keys = sorted(in_collection & in_bucket)
    unbacked = sorted(in_collection - in_bucket)
    extra = sorted(in_bucket - in_collection)
    expect_points = client.count(current).count

    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    candidate = f"{alias}_v{stamp}"

    print(f"alias         : {alias}")
    print(f"currently     : {current}  ({expect_points} points)")
    print(f"candidate     : {candidate}")
    print(f"to reindex    : {len(keys)} of {len(in_collection)} sources")
    if extra:
        print(f"SKIPPING {len(extra)} bucket object(s) with no vectors — adding "
              f"them would be a corpus change, not a migration: {extra}")
    if unbacked:
        print(f"\nBLOCKED: {len(unbacked)} indexed source(s) have no object in "
              f"the bucket: {unbacked}", file=sys.stderr)
        return 2
    if args.dry_run:
        return 0
    if not args.confirm:
        print("REFUSING without --confirm.", file=sys.stderr)
        return 2

    def etag_of(key: str) -> str:
        return container.storage.head_etag(container.storage.bucket, key)

    print("\nbuilding candidate...")
    total = build_candidate(container, settings, keys, candidate, etag_of)
    print(f"  {total} chunks indexed")

    print("\nverifying BEFORE the alias moves...")
    try:
        verify_candidate(client, candidate, expect_points=expect_points,
                         expect_dim=settings.embed_dim, expect_digest=digest)
    except VerificationFailed as e:
        print(f"\nVERIFICATION FAILED: {e}", file=sys.stderr)
        print(f"The alias still points at {current}. Live traffic is unaffected.\n"
              f"The candidate {candidate} is left in place for inspection.",
              file=sys.stderr)
        return 1
    print("  dimension, count, payload indexes and digests all verified")

    client.update_collection_aliases(change_aliases_operations=[
        qm.CreateAliasOperation(
            create_alias=qm.CreateAlias(collection_name=candidate, alias_name=alias))
    ])
    print(f"\nALIAS SWAPPED: {alias} -> {candidate}")

    if current != alias and not args.keep_old:
        client.delete_collection(current)
        print(f"dropped previous collection {current}")
    elif current == alias:
        print(f"NOTE: {current} is a real collection, not an alias target, so it "
              f"was NOT dropped — the alias now shadows it. Remove it by hand "
              f"once traffic is confirmed healthy.")

    print(f"\n    DIGEST_ENFORCEMENT_FROM={datetime.now(UTC).isoformat()}\n")
    print("Printed only because the full scroll above confirmed every point "
          "carries a digest.")
    print("Record a FRESH baseline. Pre- and post-reindex baselines are "
          "INCOMPARABLE by construction.")
    return 0


def self_test(client, alias: str, current: str, settings) -> int:
    """Force the failure: a candidate with the WRONG vector dimension.

    A verification that has only ever seen the happy path is indistinguishable
    from no verification. This proves the swap is refused and, critically, that
    the alias has not moved.
    """
    bad = f"{alias}__selftest_baddim"
    print(f"self-test: building {bad} with dimension {settings.embed_dim // 2} "
          f"(expected {settings.embed_dim})")
    before = resolve_target(client, alias)
    try:
        if client.collection_exists(bad):
            client.delete_collection(bad)
        client.create_collection(
            collection_name=bad,
            vectors_config={"dense": qm.VectorParams(
                size=settings.embed_dim // 2, distance=qm.Distance.COSINE)},
        )
        try:
            verify_candidate(client, bad, expect_points=0,
                             expect_dim=settings.embed_dim, expect_digest="x")
        except VerificationFailed as e:
            after = resolve_target(client, alias)
            print(f"  REFUSED, as required: {e}")
            print(f"  alias before={before}  after={after}")
            if before != after:
                print("  FAIL — the alias MOVED despite verification failing.",
                      file=sys.stderr)
                return 1
            print("  PASS — verification rejected it and the alias did not move.")
            return 0
        print("  FAIL — a wrong-dimension collection passed verification.",
              file=sys.stderr)
        return 1
    finally:
        try:
            if client.collection_exists(bad):
                client.delete_collection(bad)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
