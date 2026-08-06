"""Build-time assertion that the vendored tesseract language data is intact.

Runs inside the image build, immediately after the COPY, and BEFORE
`pip install` — so it uses the standard library only. A yaml dependency here
would fail the build for the wrong reason.

Finding #26. The base-image digest pins the tesseract binary; it does not pin
the traineddata. Vendoring pins it, and this asserts the vendored bytes are the
ones the manifest describes, so a corrupted or swapped file fails the BUILD
rather than silently changing OCR output — which is corpus content, and would
move every stored vector and every eval number with no diff in the repository.

The manifest is scanned with a regex rather than parsed. That keeps the
checksums in ONE file, the human-readable one, instead of duplicating them into
a machine-readable sidecar that could drift from it.
"""
import hashlib
import pathlib
import re
import sys

TESSDATA = pathlib.Path("/opt/tessdata")
_PAIR = re.compile(r"name:\s*(\S+)\s*\n\s*sha256:\s*([0-9a-f]{64})")


def main() -> int:
    manifest = TESSDATA / "MANIFEST.yaml"
    if not manifest.is_file():
        print(f"MANIFEST MISSING at {manifest}", file=sys.stderr)
        return 1

    pairs = _PAIR.findall(manifest.read_text(encoding="utf-8"))
    if not pairs:
        # A manifest that parses to nothing would make every check vacuous —
        # the same shape as a model-pin check that only asserts presence.
        print("MANIFEST UNREADABLE: no name/sha256 pairs found.", file=sys.stderr)
        return 1

    problems = []
    for name, expected in pairs:
        target = TESSDATA / name
        if not target.is_file():
            problems.append(f"{name}: missing")
            continue
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != expected:
            problems.append(f"{name}: {actual} != {expected}")

    if problems:
        print("VENDORED TESSDATA CHECKSUM MISMATCH", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    for name, _ in pairs:
        print(f"vendored tessdata verified: {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
