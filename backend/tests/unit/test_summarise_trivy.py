"""The layer split is load-bearing: it decides what gates the build.

`security-gate` fails only on application-layer findings, because those are
pinned by hash in api/requirements.txt and a commit can fix them. OS-layer
findings need a base-image digest bump, which moves the tesseract binary and
therefore OCR output, corpus content and every eval baseline.

So a misclassification is not cosmetic in either direction: an OS finding read
as application would fail the build on something no commit can fix, and an
application finding read as OS would let a fixable HIGH ship silently.
"""
from __future__ import annotations

import json
import sys

from scripts.summarise_trivy import load, main

REPORT = {
    "Results": [
        {
            "Class": "os-pkgs",
            "Vulnerabilities": [
                {"Severity": "HIGH", "PkgName": "libssl3", "FixedVersion": "3.0.1"},
                {"Severity": "CRITICAL", "PkgName": "zlib1g"},
                {"Severity": "MEDIUM", "PkgName": "ignored-by-severity"},
            ],
        },
        {
            "Class": "lang-pkgs",
            "Vulnerabilities": [
                {"Severity": "HIGH", "PkgName": "httpx", "FixedVersion": "0.28.1"},
                {"Severity": "LOW", "PkgName": "also-ignored"},
            ],
        },
    ]
}


def _run(tmp_path, report, capsys):
    path = tmp_path / "r.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    argv = sys.argv
    sys.argv = ["summarise_trivy.py", str(path)]
    try:
        code = main()
    finally:
        sys.argv = argv
    return code, capsys.readouterr().out


def _row(out: str, layer: str, severity: str, fixed: str) -> int:
    """The count on one summary row, parsed rather than string-matched.

    Matching the padded line verbatim made this test assert on column widths;
    the first version failed on a formatting difference while the classification
    it exists to check was correct.
    """
    for line in out.splitlines():
        parts = line.split()
        if parts[:3] == [layer, severity, fixed]:
            return int(parts[3])
    raise AssertionError(f"no row for {layer}/{severity}/{fixed} in:\n{out}")


def test_os_and_application_findings_are_counted_separately(tmp_path, capsys) -> None:
    code, out = _run(tmp_path, REPORT, capsys)
    assert code == 0
    assert _row(out, "os", "CRITICAL", "no-fix") == 1
    assert _row(out, "os", "HIGH", "fixable") == 1
    assert _row(out, "application", "HIGH", "fixable") == 1
    # The one number the gate's scope depends on.
    assert "Application-layer HIGH/CRITICAL: 1." in out


def test_medium_and_low_are_excluded(tmp_path, capsys) -> None:
    _, out = _run(tmp_path, REPORT, capsys)
    assert "ignored-by-severity" not in out
    assert "also-ignored" not in out


def test_package_names_are_printed_because_trivy_reports_presence_not_use(
    tmp_path, capsys
) -> None:
    """Trivy cannot tell you whether a vulnerable package is ever imported.

    The names are the only thing that lets a human make that call, so their
    absence would make the report unactionable.
    """
    _, out = _run(tmp_path, REPORT, capsys)
    assert "httpx" in out
    assert "libssl3" in out


def test_a_clean_report_says_so_rather_than_printing_an_empty_table(
    tmp_path, capsys
) -> None:
    code, out = _run(tmp_path, {"Results": []}, capsys)
    assert code == 0
    assert "No HIGH or CRITICAL findings." in out


def test_the_reporter_never_gates(tmp_path, capsys) -> None:
    """Exit 0 even with CRITICALs present — the gate is a separate job.

    If this ever returned non-zero, the scan job would start failing the build
    on OS findings, which is precisely the conflation the split exists to undo.
    """
    code, _ = _run(tmp_path, REPORT, capsys)
    assert code == 0


def test_load_reads_the_report(tmp_path) -> None:
    path = tmp_path / "r.json"
    path.write_text(json.dumps(REPORT), encoding="utf-8")
    assert load(str(path))["Results"][0]["Class"] == "os-pkgs"
