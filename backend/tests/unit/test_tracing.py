"""Phase 4.2: a trace id is a correlation aid, never an identity.

The browser supplies it, so it is attacker-controlled. These tests pin that it
is sanitised rather than trusted, and that a bad one degrades to a fresh id
instead of failing the request.
"""
from __future__ import annotations

import pytest

from core.tracing import TRACE_HEADER, adopt_trace_id, new_trace_id


def test_a_well_formed_id_is_adopted() -> None:
    assert adopt_trace_id("abc123-DEF_456.789") == "abc123-DEF_456.789"


def test_a_missing_id_is_minted() -> None:
    minted = adopt_trace_id(None)
    assert minted and minted != adopt_trace_id(None)


@pytest.mark.parametrize("hostile", [
    "line1\nline2",                 # forges a second log line
    "a" * 500,                      # bloats every log record and the DLQ entry
    '{"injected": true}',           # smuggles structure into a JSON log field
    "../../etc/passwd",
    "",
    "trace id with spaces",
])
def test_hostile_ids_are_replaced_not_trusted(hostile: str) -> None:
    """It lands in structured logs and in the DLQ payload, so an unbounded or
    newline-bearing value could forge entries or bloat a Redis record."""
    adopted = adopt_trace_id(hostile)
    assert adopted != hostile
    assert len(adopted) == 12 and adopted.isalnum()


def test_a_bad_id_never_fails_the_request() -> None:
    """A malformed debugging header must not break an upload."""
    assert adopt_trace_id("\n" * 100)


def test_the_header_name_is_stable() -> None:
    """The proxy forwards this exact name; renaming it silently breaks the
    browser-to-worker chain with no error anywhere."""
    assert TRACE_HEADER == "X-Trace-Id"


def test_minted_ids_are_short_and_unique() -> None:
    ids = {new_trace_id() for _ in range(200)}
    assert len(ids) == 200
    assert all(len(i) == 12 for i in ids)
