"""Snapshot a Qdrant collection AND prove the snapshot restores.

    docker compose exec api python scripts/snapshot.py --verify

Why this exists: `scripts/reindex.py` rewrites every point IN PLACE. Point IDs
are `uuid5(source:etag:chunk_seq)` and therefore stable, which is what makes the
reindex idempotent and re-runnable — and also what means there is no second copy
of the old vectors anywhere. Without a snapshot the pre-reindex state is
unrecoverable.

A snapshot that has never been restored is a backup nobody has tested. `--verify`
recovers it into a THROWAWAY collection, compares the point count against the
source, and deletes the throwaway. The original is never touched by the check.

    python scripts/snapshot.py                    # create only
    python scripts/snapshot.py --verify           # create, restore-test, report
    python scripts/snapshot.py --list             # what snapshots exist
    python scripts/snapshot.py --collection X     # default: QDRANT_COLLECTION
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import get_settings  # noqa: E402
from integrations.qdrant_store import QdrantVectorStore  # noqa: E402

VERIFY_SUFFIX = "__restore_check"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", default=None)
    parser.add_argument("--verify", action="store_true",
                        help="restore into a throwaway collection and compare counts")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    collection = args.collection or settings.qdrant_collection
    client = QdrantVectorStore(settings)._get_client()

    if args.list:
        for snap in client.list_snapshots(collection):
            print(f"  {snap.name}  {snap.size} bytes  {snap.creation_time}")
        return 0

    source_count = client.count(collection).count
    print(f"collection : {collection}")
    print(f"points     : {source_count}")

    snapshot = client.create_snapshot(collection_name=collection, wait=True)
    if snapshot is None:
        print("Snapshot creation returned nothing.", file=sys.stderr)
        return 1
    print(f"snapshot   : {snapshot.name}  ({snapshot.size} bytes)")

    if not args.verify:
        print("\nNOT VERIFIED. An untested backup is not a backup — re-run with "
              "--verify before relying on it.")
        return 0

    # Restore into a throwaway. The source collection is never touched, so a
    # failed restore costs nothing beyond the check itself.
    check = f"{collection}{VERIFY_SUFFIX}"
    url = f"file:///qdrant/snapshots/{collection}/{snapshot.name}"
    print(f"\nrestoring into {check} ...")
    try:
        if client.collection_exists(check):
            client.delete_collection(check)
        client.recover_snapshot(collection_name=check, location=url, wait=True)
        restored = client.count(check).count
        print(f"restored   : {restored} points")
        if restored != source_count:
            print(f"\nRESTORE VERIFICATION FAILED: {restored} points restored, "
                  f"{source_count} expected.", file=sys.stderr)
            return 1
        print("\nVERIFIED — the snapshot restores to an identical point count.")
        print(f"Snapshot location inside the qdrant container:\n    {url}")
        return 0
    finally:
        try:
            if client.collection_exists(check):
                client.delete_collection(check)
                print(f"cleaned up {check}")
        except Exception as e:  # never leave the check collection behind silently
            print(f"WARNING: could not delete {check}: {e}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
