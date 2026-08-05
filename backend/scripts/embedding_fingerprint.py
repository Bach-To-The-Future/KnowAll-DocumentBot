"""Capture or verify an embedding fingerprint across a runtime change.

    python scripts/embedding_fingerprint.py --capture   # before
    python scripts/embedding_fingerprint.py --verify    # after

A model digest moving tells you the artifact changed. It does NOT tell you
whether the VECTORS changed, and those are different problems:

    same vectors     a republish carrying the same weights — metadata moved,
                     the collection is intact, and updating the pin absorbs it
    divergent        re-quantization. Every stored vector was produced by a
                     function that no longer exists, the collection is
                     invalidated, and a reindex plus fresh baselines follows

Do not assume which case you are in. This measures it: a fixed probe text is
embedded and the vector committed, so the same text can be re-embedded later
and compared by cosine.

The probe text is deliberately boring and fixed forever. Changing it destroys
the comparison.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import UTC, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import get_settings  # noqa: E402
from core.model_identity import fetch_ollama_digest  # noqa: E402
from integrations.embeddings import build_embedder  # noqa: E402

# NEVER change this string. It is the control.
PROBE = ("Records are retained for seven years from the date of creation. "
         "Disposal requires written authorisation from the records officer.")

# Overridable because /app is read-only to the non-root runtime user; the
# capture is written somewhere writable and copied into the repo from outside.
FINGERPRINT = os.getenv(
    "FINGERPRINT_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "eval", "baselines", "embedding-fingerprint.json"),
)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    digest = fetch_ollama_digest(settings, settings.embed_model)
    vector = build_embedder(settings).embed_query(PROBE)

    if args.capture:
        record = {
            "probe_text": PROBE,
            "embed_model": settings.embed_model,
            "embed_model_digest": digest,
            "embed_dim": len(vector),
            "vector": vector,
            "captured_at": datetime.now(UTC).isoformat(),
            "why": ("Control for a runtime upgrade. Re-embed PROBE and compare by "
                    "cosine: 1.0 means the weights are unchanged and only metadata "
                    "moved; anything less means re-quantization and the collection "
                    "is invalidated."),
        }
        with open(FINGERPRINT, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2)
        print(f"captured   model={settings.embed_model}")
        print(f"           digest={digest}")
        print(f"           dim={len(vector)}  first 4={vector[:4]}")
        print(f"           -> {FINGERPRINT}")
        return 0

    if not args.verify:
        print("Pass --capture or --verify.", file=sys.stderr)
        return 2

    with open(FINGERPRINT, encoding="utf-8") as fh:
        old = json.load(fh)

    print(f"           BEFORE                     AFTER")
    print(f"digest     {str(old['embed_model_digest'])[:24]}   {str(digest)[:24]}")
    print(f"dim        {old['embed_dim']:<26} {len(vector)}")

    if len(vector) != old["embed_dim"]:
        print("\nDIMENSION CHANGED — the collection is unusable. Reindex required.",
              file=sys.stderr)
        return 1

    similarity = cosine(old["vector"], vector)
    exact = old["vector"] == vector
    print(f"cosine     {similarity:.12f}")
    print(f"byte-exact {exact}")

    print()
    if exact or similarity > 0.999999:
        print("VECTORS UNCHANGED.")
        if old["embed_model_digest"] != digest:
            print("  The digest moved but the vectors did not: a republish carrying")
            print("  the same weights. Update EXPECTED_EMBED_MODEL_DIGEST to the new")
            print("  value. The collection is INTACT and baselines stay comparable.")
        else:
            print("  Digest and vectors both unchanged. Nothing to do.")
        return 0

    print("VECTORS DIVERGED — this is re-quantization, not a republish.")
    print(f"  cosine {similarity:.6f} against the stored probe.")
    print("  Every vector in the collection was produced by a function that no")
    print("  longer exists. The collection is INVALIDATED: a reindex and fresh")
    print("  baselines are required, and that is a maintainer decision.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
