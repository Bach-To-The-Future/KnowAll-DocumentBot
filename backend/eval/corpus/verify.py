"""Corpus integrity gate. Hard-fails before any eval run.

A baseline is only comparable if the corpus that produced it is byte-identical.
This script re-hashes every file listed in MANIFEST.yaml and refuses to pass on
any mismatch, missing file, or untracked extra file in the corpus tree.

Usage:
    python eval/corpus/verify.py            # verify, exit 1 on any drift
    python eval/corpus/verify.py --print-hash   # emit the manifest hash only

The manifest hash it prints is one element of the provenance tuple recorded in
every baseline (see eval/baselines/README.md); the comparator refuses to diff
baselines whose tuples differ.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any

CORPUS_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = CORPUS_DIR / "MANIFEST.yaml"
# Files that live in the corpus tree but are not corpus documents.
NON_DOCUMENT_NAMES = {"MANIFEST.yaml", "verify.py", "generate_tier_b.py", "README.md"}


def _load_manifest() -> dict[str, Any]:
    try:
        import yaml
    except ModuleNotFoundError:  # pragma: no cover - environment guard
        sys.exit("PyYAML is required to verify the corpus (pip install pyyaml).")
    with MANIFEST_PATH.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict) or "documents" not in data:
        sys.exit(f"{MANIFEST_PATH} is malformed: expected a top-level 'documents' list.")
    return data


def load_manifest() -> dict[str, Any]:
    """Public accessor — eval/ingest_corpus.py walks the document list."""
    return _load_manifest()


def is_ingested(entry: dict[str, Any]) -> bool:
    """Does this document go into the index?

    Default true. A document can be part of the corpus DEFINITION without being
    part of the INDEX: b04-wide-row.csv is a single row wider than the embedding
    window, so the token-budget guard refuses it, and it is kept as a fixture
    proving that boundary is reachable rather than deleted.

    This is the one place that decides. eval/ingest_corpus.py and
    eval/run_eval.py both call it, so what is indexed and which golden entries
    are scorable cannot drift apart.
    """
    return bool(entry.get("ingest", True))


def ingested_documents(manifest: dict[str, Any] | None = None) -> set[str]:
    """Basenames of the documents that actually reach the index."""
    m = manifest if manifest is not None else _load_manifest()
    return {Path(e["path"]).name for e in m["documents"] if is_ingested(e)}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest_hash() -> str:
    """Hash of the manifest file itself — identifies the corpus definition."""
    return sha256_file(MANIFEST_PATH)


REQUIRED_FIELDS = (
    "path", "sha256", "format", "language", "parallel_id",
    "tier", "license", "source_url", "retrieved", "exercises",
)


def verify() -> int:
    manifest = _load_manifest()
    documents = manifest["documents"]
    errors: list[str] = []
    listed: set[Path] = set()

    for entry in documents:
        missing_fields = [f for f in REQUIRED_FIELDS if f not in entry]
        if missing_fields:
            errors.append(f"{entry.get('path', '<no path>')}: missing fields {missing_fields}")
            continue

        # `ingest` decides whether a document reaches the index, so a typo
        # ("no", "false", 0) must not be read as truthy and silently index a
        # document the guard would refuse.
        if "ingest" in entry and not isinstance(entry["ingest"], bool):
            errors.append(
                f"{entry['path']}: 'ingest' must be a YAML boolean, got "
                f"{entry['ingest']!r} ({type(entry['ingest']).__name__})"
            )

        rel = Path(entry["path"])
        target = CORPUS_DIR / rel
        listed.add(target.resolve())

        if not target.is_file():
            errors.append(f"{rel}: listed in manifest but MISSING on disk")
            continue

        actual = sha256_file(target)
        if actual != entry["sha256"]:
            errors.append(
                f"{rel}: sha256 MISMATCH\n"
                f"    manifest: {entry['sha256']}\n"
                f"    on disk : {actual}"
            )

    # Untracked extras matter as much as missing files: an unlisted document
    # would be ingested and silently change every retrieval metric.
    for path in sorted(CORPUS_DIR.rglob("*")):
        if not path.is_file():
            continue
        if path.name in NON_DOCUMENT_NAMES or "__pycache__" in path.parts:
            continue
        if path.resolve() not in listed:
            errors.append(f"{path.relative_to(CORPUS_DIR)}: present on disk but NOT in manifest")

    if errors:
        print("CORPUS VERIFICATION FAILED\n", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        print(
            f"\n{len(errors)} problem(s). Refusing to proceed: an eval run against a "
            f"drifted corpus produces numbers that cannot be compared to any baseline.",
            file=sys.stderr,
        )
        return 1

    by_tier: dict[str, int] = {}
    for entry in documents:
        by_tier[entry["tier"]] = by_tier.get(entry["tier"], 0) + 1
    print(f"corpus OK: {len(documents)} documents verified " + str(by_tier))
    not_ingested = [e["path"] for e in documents if not is_ingested(e)]
    if not_ingested:
        # Stated on every run: the difference between the corpus and the index
        # is the kind of thing that becomes invisible three months later.
        print(f"  {len(documents) - len(not_ingested)} indexed, "
              f"{len(not_ingested)} kept as fixtures only:")
        for path in not_ingested:
            print(f"    - {path} (ingest: false)")
    print(f"manifest_sha256: {manifest_hash()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-hash", action="store_true",
                        help="print the manifest sha256 and exit")
    args = parser.parse_args()
    if args.print_hash:
        print(manifest_hash())
        return 0
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
