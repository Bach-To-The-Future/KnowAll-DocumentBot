"""Ingest the evaluation corpus into its own Qdrant collection.

A baseline is only reproducible if the step that produced the index is too, so
this is a script rather than a sequence of commands someone once ran.

    docker compose exec -e QDRANT_COLLECTION=knowall_eval api \
        python eval/ingest_corpus.py

SEPARATE COLLECTION, ALWAYS. The default collection holds real user documents.
Ingesting the eval corpus alongside them would add unmanifested distractors to
every eval query — the numbers would not be reproducible from MANIFEST.yaml,
which is the one thing the manifest exists to guarantee. This script refuses to
run against the default collection name for that reason.

ETAG = THE MANIFEST SHA256. Point IDs are uuid5(source:etag:chunk_seq), so
using the manifest's own hash as the etag makes the point IDs a pure function
of the corpus definition: re-running is idempotent, two machines produce
identical IDs, and a document edited without updating the manifest is caught by
verify() before it can reach the index.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import get_settings  # noqa: E402
from core.model_identity import verify_embedding_model  # noqa: E402
from eval.corpus import verify as corpus_verify  # noqa: E402
from services.container import build_container  # noqa: E402

DEFAULT_COLLECTION = "knowall_collection"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-default-collection", action="store_true",
                        help="ingest into the production collection anyway "
                             "(you almost certainly do not want this)")
    args = parser.parse_args()

    settings = get_settings()
    if settings.qdrant_collection == DEFAULT_COLLECTION and not args.allow_default_collection:
        print(
            f"REFUSING to ingest the eval corpus into '{DEFAULT_COLLECTION}'.\n"
            f"  That collection holds real documents; mixing the corpus in makes\n"
            f"  every eval number depend on content no manifest describes.\n"
            f"  Re-run with QDRANT_COLLECTION set to a dedicated collection.",
            file=sys.stderr,
        )
        return 2

    if corpus_verify.verify() != 0:
        return 2
    verify_embedding_model(settings, context="corpus ingest")

    manifest = corpus_verify.load_manifest()
    etag = corpus_verify.manifest_hash()
    container = build_container(settings)

    print(f"collection: {settings.qdrant_collection}")
    print(f"etag (manifest sha256): {etag}\n")

    total = 0
    for doc in manifest["documents"]:
        path = str(corpus_verify.CORPUS_DIR / doc["path"])
        count = container.ingestion.process_document(path, etag=etag)
        total += count
        print(f"  [{doc['tier']}] {doc['path']:<34} {count:>5} chunks")

    print(f"\n{total} chunks indexed from {len(manifest['documents'])} documents.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
