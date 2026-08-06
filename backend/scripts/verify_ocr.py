"""Finding #26: are the VENDORED traineddata the ones tesseract actually reads?

    docker compose exec api python scripts/verify_ocr.py

Three checks, because the failure mode is silent. A traineddata that cannot be
loaded does not necessarily error — tesseract may fall back to another copy,
or emit plausible-looking nonsense. Word counts would pass on garbage.

  1. MANIFEST     the files on disk match the committed sha256 exactly
  2. RESOLUTION   TESSDATA_PREFIX points at the vendored directory, and the
                  system copy is NOT shadowing it. "The right file is present"
                  is not evidence it is the one being read — the same
                  coincidence that made the HuggingFace revision pin look like
                  it worked when it did not (handoff §1c).
  3. CONTENT      OCR on the tier-B image-only PDFs still contains KNOWN
                  STRINGS from the source documents, in EN and in FR.
"""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.disable(logging.INFO)

VENDOR_DIR = "/opt/tessdata"
CORPUS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "eval", "corpus", "tier-b")

# Verbatim from generate_tier_b.py. Word counts would pass on garbage; these
# would not.
KNOWN = {
    "b09-scanned-notice.pdf": ["ARCHIVED NOTICE", "heritage grant", "75000"],
    "b13-avis-archive-fr.pdf": ["AVIS ARCHIVE", "plafond", "subvention", "31 mars"],
}


def load_manifest() -> dict:
    import yaml
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "vendor", "tessdata", "MANIFEST.yaml")
    with open(path, encoding="utf-8") as fh:
        return dict(yaml.safe_load(fh))


def main() -> int:
    failures = 0
    manifest = load_manifest()

    print("=== 1. MANIFEST — do the vendored files match their checksums? ===")
    for entry in manifest["files"]:
        target = os.path.join(VENDOR_DIR, entry["name"])
        if not os.path.isfile(target):
            print(f"  MISSING {target}")
            failures += 1
            continue
        digest = hashlib.sha256(open(target, "rb").read()).hexdigest()
        ok = digest == entry["sha256"]
        print(f"  {'ok  ' if ok else 'FAIL'} {entry['name']}  {digest[:16]}…")
        failures += not ok

    print("\n=== 2. RESOLUTION — is tesseract READING these, or a system copy? ===")
    prefix = os.getenv("TESSDATA_PREFIX", "")
    print(f"  TESSDATA_PREFIX = {prefix!r}")
    if prefix.rstrip("/") != VENDOR_DIR:
        print(f"  FAIL — expected {VENDOR_DIR}")
        failures += 1
    out = subprocess.run(["tesseract", "--list-langs"], capture_output=True,
                         text=True, timeout=60)
    listing = (out.stdout + out.stderr).strip()
    print(f"  tesseract reports: {listing.splitlines()[0] if listing else '<nothing>'}")
    if VENDOR_DIR not in listing:
        print("  FAIL — tesseract is listing languages from somewhere else. The "
              "vendored files would sit unused beside a system copy.")
        failures += 1
    else:
        print("  ok   — resolution confirmed against the vendored directory")

    print("\n=== 3. CONTENT — known strings, EN and FR ===")
    from extraction.options import ExtractStrategy
    for name, needles in KNOWN.items():
        path = os.path.join(CORPUS, name)
        if not os.path.isfile(path):
            print(f"  {name}: MISSING from the corpus")
            failures += 1
            continue
        nodes = list(ExtractStrategy.get_extractor(path).extract_and_chunk(path))
        text = " ".join(n.text for n in nodes)
        missing = [n for n in needles if n.lower() not in text.lower()]
        print(f"  {name}  {len(text)} chars")
        print(f"    {text[:120]!r}")
        if missing:
            print(f"    FAIL — missing {missing}. OCR produced output but not the "
                  f"source text: this is the SILENT GARBAGE mode.")
            failures += 1
        else:
            print(f"    ok   — all {len(needles)} known strings present")

    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{failures} CHECK(S) FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
