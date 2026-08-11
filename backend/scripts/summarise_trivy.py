"""Summarise a Trivy JSON report by layer, so a reader can act on it.

    python scripts/summarise_trivy.py trivy-report.json

WHY A FILE RATHER THAN AN INLINE HEREDOC IN ci.yml
An embedded multi-line command has broken this repository's build config twice
already (finding #25, and the tessdata check that became api/verify_tessdata.py).
The first attempt at this summary was a `python3 - <<'EOF'` block inside a YAML
`run:` scalar and it broke the workflow's YAML parse. Same lesson, third time:
put it in a file that a linter and a test can see.

WHY SPLIT BY LAYER
The two classes carry different obligations and a single count hides that:

  application (lang-pkgs)  Python dependencies, pinned by hash in
                           api/requirements.txt. Fixable in a commit. These
                           gate the build.
  os                       Debian packages from the base image. Not fixable
                           without moving the base-image digest, which moves the
                           tesseract binary, therefore OCR output, therefore
                           corpus content, therefore every stored vector and
                           every eval baseline (findings #25/#26). That is a
                           proposal, not a CI fix.

`FixedVersion` is reported alongside, because "HIGH with no upstream fix" and
"HIGH you are simply behind on" are also different obligations.

TRIVY REPORTS PRESENCE, NOT REACHABILITY. A CVE in a package that ships but is
never imported is not the same as one in httpx or pdfplumber. This script cannot
tell you which is which; it prints the package names so a human can.
"""
from __future__ import annotations

import collections
import json
import sys
from typing import Any

SEVERITIES = ("CRITICAL", "HIGH")


def load(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
    return data


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: summarise_trivy.py <trivy-report.json>", file=sys.stderr)
        return 2

    report = load(sys.argv[1])
    counts: collections.Counter[tuple[str, str, str]] = collections.Counter()
    packages: dict[str, set[str]] = {"application": set(), "os": set()}

    for result in report.get("Results", []):
        layer = "application" if result.get("Class") == "lang-pkgs" else "os"
        for vuln in result.get("Vulnerabilities") or []:
            severity = str(vuln.get("Severity", ""))
            if severity not in SEVERITIES:
                continue
            fixed = "fixable" if vuln.get("FixedVersion") else "no-fix"
            counts[(layer, severity, fixed)] += 1
            packages[layer].add(str(vuln.get("PkgName", "?")))

    if not counts:
        print("No HIGH or CRITICAL findings.")
        return 0

    print("HIGH/CRITICAL by layer:")
    for key in sorted(counts):
        layer, severity, fixed = key
        print(f"  {layer:12s} {severity:9s} {fixed:8s} {counts[key]}")

    for layer in ("application", "os"):
        names = sorted(packages[layer])
        if names:
            print(f"\n{layer} packages ({len(names)}): {', '.join(names[:25])}"
                  + (" …" if len(names) > 25 else ""))

    app_total = sum(v for k, v in counts.items() if k[0] == "application")
    print(
        f"\nApplication-layer HIGH/CRITICAL: {app_total}. These gate the build — "
        f"they are pinned by hash in api/requirements.txt and a commit can fix "
        f"them.\nOS-layer findings need a base-image digest bump, which moves OCR "
        f"output and every eval baseline. See docs/FINAL_AUDIT.md."
    )
    # Always 0: this is the REPORT. The gate is a separate job, deliberately.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
