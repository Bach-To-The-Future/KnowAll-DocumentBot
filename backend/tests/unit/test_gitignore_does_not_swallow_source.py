"""No source file may be hidden by .gitignore.

WHY THIS EXISTS

A clean clone of this repository could not be built. Two unanchored patterns
matched at any depth and swallowed four source files that had therefore never
been committed:

    *documents/  ->  frontend/src/app/documents/page.tsx
                     frontend/src/components/documents/DocumentDashboard.tsx
    models/      ->  backend/models/__init__.py
                     backend/models/schemas.py

`backend/models/` is a documented architectural layer. The stack worked only
because the untracked files happened to exist in one working copy.

Phase 0 of the remediation verified `.gitignore` coverage — it confirmed each
pattern matched its intended target, and never asked what ELSE each pattern
matched. That is the gap this closes: a guard must be checked for firing only
on the right things, not merely for firing.

WHY IT IS SHAPED LIKE THIS

The real assertion (`test_no_source_file_is_ignored`) can only ever pass on a
healthy tree, so on its own it would be indistinguishable from a test that
asserts nothing. `test_the_detector_actually_detects` plants a known-bad path
through the same classifier and requires it to be flagged.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

SOURCE_SUFFIXES = {".py", ".ts", ".tsx"}

# Ignored trees that legitimately contain source-shaped files: third-party
# packages, virtualenvs, build output and tool caches. Anything ignored OUTSIDE
# these is our own code being hidden.
VENDOR_PARTS = {
    "node_modules",
    ".venv",
    "venv",
    ".next",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "site-packages",
    "dist",
    "build",
    ".git",
}


def is_hidden_source(relpath: str) -> bool:
    """True if `relpath` is our own source and is being ignored."""
    path = Path(relpath)
    if path.suffix not in SOURCE_SUFFIXES:
        return False
    return not (VENDOR_PARTS & set(path.parts))


def _ignored_files() -> list[str]:
    # The api image ships no git, so this must SKIP there rather than fail —
    # a missing binary raises FileNotFoundError, which is not the same code
    # path as a non-zero exit and was not handled on the first attempt.
    try:
        result = subprocess.run(
            ["git", "ls-files", "--others", "--ignored", "--exclude-standard"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"git not available in this environment: {exc}")
    if result.returncode != 0:
        pytest.skip(f"not a git repository: {result.stderr.strip()[:120]}")
    return [line for line in result.stdout.splitlines() if line.strip()]


def test_no_source_file_is_ignored() -> None:
    hidden = sorted(p for p in _ignored_files() if is_hidden_source(p))
    assert not hidden, (
        "These source files are excluded by .gitignore and would be MISSING from a "
        "clean clone:\n  " + "\n  ".join(hidden) +
        "\n\nAn unanchored pattern (e.g. `models/` rather than `/models/`) matches at "
        "any depth. Anchor it or add a negation."
    )


@pytest.mark.parametrize(
    "relpath",
    [
        "backend/models/schemas.py",
        "frontend/src/app/documents/page.tsx",
        "frontend/src/components/documents/DocumentDashboard.tsx",
        "backend/services/query.py",
    ],
)
def test_the_detector_actually_detects(relpath: str) -> None:
    """The four real regressions, fed straight to the classifier.

    Without this, a bug that made `is_hidden_source` always return False would
    leave the suite green while the guard protected nothing.
    """
    assert is_hidden_source(relpath) is True


@pytest.mark.parametrize(
    "relpath",
    [
        "frontend/node_modules/next/index.d.ts",
        "backend/.venv/lib/site-packages/foo.py",
        "backend/services/__pycache__/query.cpython-312.pyc",
        "backend/documents/some-upload.pdf",
        "frontend/.next/types/app.ts",
    ],
)
def test_vendor_and_non_source_are_not_flagged(relpath: str) -> None:
    """And it must not fire on the things that are ignored on purpose."""
    assert is_hidden_source(relpath) is False
