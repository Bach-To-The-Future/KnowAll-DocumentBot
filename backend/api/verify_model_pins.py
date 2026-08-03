"""Build-time assertion that fastembed used the PINNED model revisions.

Runs inside the image build, after snapshot_download() has fetched the exact
commits and after the fastembed constructors have run. If fastembed resolved a
repo's default branch to something newer than the pin, the cached snapshot
directory for the pinned commit will not exist and the BUILD FAILS here —
rather than shipping an image whose rerank scores, and therefore every eval
number, silently moved.

Why an assertion and not HF_HUB_OFFLINE=1: fastembed does not resolve models
through the plain huggingface_hub cache layout, so offline mode fails outright
with "Could not load model Qdrant/bm25 from any source". Verifying after the
fact is what actually holds the pin.
"""
import pathlib
import sys

CACHE = pathlib.Path("/opt/models")

PINS = {
    "models--Qdrant--bm25": sys.argv[1],
    "models--BAAI--bge-reranker-base": sys.argv[2],
}


def main() -> int:
    problems: list[str] = []
    for repo, pinned in PINS.items():
        snapshots = CACHE / repo / "snapshots"
        present = sorted(p.name for p in snapshots.iterdir()) if snapshots.is_dir() else []

        if pinned not in present:
            problems.append(f"{repo}: pinned {pinned} not cached; present={present}")
            continue

        # The pinned snapshot merely EXISTING is not sufficient: step 1
        # (snapshot_download) guarantees that on its own. If fastembed then
        # resolved the default branch to a newer commit, it would sit here as
        # a SECOND snapshot and be the one actually loaded — while a
        # presence-only check passed. Requiring exactly one snapshot is what
        # makes "fastembed used something other than the pin" detectable.
        if len(present) != 1:
            problems.append(
                f"{repo}: {len(present)} snapshots cached {present}; expected only the "
                f"pinned {pinned}. fastembed resolved a revision other than the pin."
            )

    if problems:
        print("MODEL REVISION PIN VIOLATED", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    for repo, pinned in PINS.items():
        print(f"model revision verified: {repo} @ {pinned} (sole cached snapshot)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
