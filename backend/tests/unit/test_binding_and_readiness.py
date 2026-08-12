"""R1.4 (port binding) and R1.5 (/ready reachability + honest remediation).

Both were guards that read a declaration rather than a fact:

  R1.4  the trust/port check read KNOWALL_API_PORT_PUBLISHED, which NOTHING
        set — it appeared once outside the checker, in a compose COMMENT — so
        it passed on a genuinely published port.
  R1.5  /ready's degraded message told operators that restarting the API calls
        `ensure_ready`. It did not; `ensure_ready` appeared nowhere in the API
        startup path, and its only occurrence under api/ was inside that string.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from api.dependencies import READONLY_PATH_PREFIXES
from core.config import Settings
from core.exceptions import ConfigurationError
from core.startup_checks import BINDING_VAR, check_proxy_trust_coherent

REPO = pathlib.Path(__file__).resolve().parents[3]


def settings(**kw):
    return Settings(_env_file=None, api_key="real", **kw)


# --- R1.4 -------------------------------------------------------------------

def test_AN_ABSENT_DECLARATION_NOW_FAILS_CLOSED(monkeypatch) -> None:
    """The defect itself. Unset used to mean "not published" and therefore
    "safe"; absence of evidence was read as evidence of absence."""
    monkeypatch.delenv(BINDING_VAR, raising=False)
    with pytest.raises(ConfigurationError) as exc:
        check_proxy_trust_coherent(settings(trust_proxy_identity=True))
    assert "cannot be established" in str(exc.value)


def test_a_published_binding_is_refused(monkeypatch) -> None:
    monkeypatch.setenv(BINDING_VAR, "published")
    with pytest.raises(ConfigurationError) as exc:
        check_proxy_trust_coherent(settings(trust_proxy_identity=True))
    assert "published to the host" in str(exc.value)


@pytest.mark.parametrize("value", ["loopback", "127.0.0.1", "none", "unpublished"])
def test_a_loopback_binding_starts(monkeypatch, value) -> None:
    """The control: the guard must not simply refuse everything."""
    monkeypatch.setenv(BINDING_VAR, value)
    check_proxy_trust_coherent(settings(trust_proxy_identity=True))


def test_trust_off_needs_no_declaration(monkeypatch) -> None:
    """With trust off, caller-supplied identity is not believed, so exposure
    is not this check's business."""
    monkeypatch.delenv(BINDING_VAR, raising=False)
    check_proxy_trust_coherent(settings(trust_proxy_identity=False))


def test_the_error_explains_why_it_cannot_just_look(monkeypatch) -> None:
    """A required declaration reads as bureaucracy unless the reason is given.

    Measured: with host mappings 127.0.0.1:8000->8000 and 0.0.0.0:8000->8000,
    the container's own socket view is byte-identical.
    """
    monkeypatch.delenv(BINDING_VAR, raising=False)
    with pytest.raises(ConfigurationError) as exc:
        check_proxy_trust_coherent(settings(trust_proxy_identity=True))
    assert "network namespace" in exc.value.detail


def test_the_dead_variable_is_no_longer_READ_or_SET() -> None:
    """KNOWALL_API_PORT_PUBLISHED must not be consulted or declared anywhere.

    It may still be NAMED in a comment explaining why it was replaced — that is
    the historical record, and deleting it would leave the next reader to
    rediscover why a declaration is required. What must not survive is code
    that reads it or config that sets it.

    (The first version of this test asserted the string was absent entirely and
    failed on the comment documenting its removal.)
    """
    def live_lines(path: pathlib.Path) -> list[str]:
        """Lines that DO something. Comments are the historical record."""
        return [ln for ln in path.read_text(encoding="utf-8").splitlines()
                if not ln.strip().startswith("#")]

    for path in (REPO / "backend" / "core" / "startup_checks.py",
                 REPO / "docker-compose.yml"):
        offenders = [ln.strip() for ln in live_lines(path)
                     if "KNOWALL_API_PORT_PUBLISHED" in ln]
        assert not offenders, f"{path.name} still uses it: {offenders}"


# --- R1.5 -------------------------------------------------------------------

def test_ready_is_on_the_backend_readonly_surface() -> None:
    assert "/ready" in READONLY_PATH_PREFIXES


def test_ready_is_on_the_proxy_allowlist() -> None:
    """The two lists are enforced independently and must agree — /ready was on
    NEITHER, so the 2.6 readiness endpoint was unreachable from a browser."""
    route = (REPO / "frontend" / "src" / "app" / "api" / "backend" /
             "[...path]" / "route.ts").read_text(encoding="utf-8")
    # The declaration is `const READ_ONLY: RegExp[] = [ ... ];` — splitting on
    # the first "]" lands inside `RegExp[]`, not the array. Take the array.
    read_only = route.split("const READ_ONLY")[1].split("= [")[1].split("];")[0]
    assert re.search(r"\^ready\$", read_only), read_only


def test_the_remediation_text_is_TRUE() -> None:
    """It must name a mechanism that exists.

    The old text said restarting calls `ensure_ready`. Nothing in api/ called
    it. Softening the wording would have been the alias-branch pattern with
    better grammar; the fix is that the API now genuinely calls it.
    """
    main = (REPO / "backend" / "api" / "main.py").read_text(encoding="utf-8")
    assert "vector_store.ensure_ready" in main, (
        "/ready promises that restarting repairs the indexes; api/main.py must "
        "actually call ensure_ready for that to be true."
    )


def test_the_remediation_text_also_names_the_fallback() -> None:
    system = (REPO / "backend" / "api" / "routers" / "system.py").read_text(encoding="utf-8")
    degraded = system.split("missing_payload_indexes")[2]
    assert "ingest" in degraded and "reindex" in degraded
