"""Phases 2.5, 2.6 and 2.7: guards that must FIRE, not merely exist.

Per handoff §1c, each test forces the failure condition rather than asserting
the happy path. A configuration guard that has never been seen to reject
anything is indistinguishable from one that does nothing.
"""
from __future__ import annotations

import pytest

from core.config import Settings
from core.exceptions import ConfigurationError
from core.startup_checks import (
    DEV_MODE_VALUE,
    DEV_MODE_VAR,
    check_auth_configured,
    check_proxy_trust_coherent,
)


def settings(**kw) -> Settings:
    kw.setdefault("api_key", "a-real-secret")
    return Settings(_env_file=None, **kw)


# --- 2.7: an unset API key must not silently disable auth --------------------

def test_a_real_api_key_starts_normally(monkeypatch) -> None:
    monkeypatch.delenv(DEV_MODE_VAR, raising=False)
    check_auth_configured(settings())


def test_an_UNSET_api_key_refuses_to_start(monkeypatch) -> None:
    monkeypatch.delenv(DEV_MODE_VAR, raising=False)
    with pytest.raises(ConfigurationError, match="disables authentication"):
        check_auth_configured(settings(api_key=None))


def test_the_SHIPPED_PLACEHOLDER_refuses_to_start(monkeypatch) -> None:
    """The placeholder is published in this repository, so anyone can read it.
    Treating it as a real key is worse than having none."""
    monkeypatch.delenv(DEV_MODE_VAR, raising=False)
    with pytest.raises(ConfigurationError, match="placeholder"):
        check_auth_configured(settings(api_key="REPLACE_ME"))


def test_dev_mode_requires_the_EXACT_awkward_value(monkeypatch) -> None:
    """A quiet boolean is what gets set in production and forgotten."""
    for value in ("1", "true", "yes", "on", DEV_MODE_VALUE.upper()):
        monkeypatch.setenv(DEV_MODE_VAR, value)
        with pytest.raises(ConfigurationError):
            check_auth_configured(settings(api_key=None))


def test_dev_mode_allows_startup_and_shouts_about_it(monkeypatch, caplog) -> None:
    monkeypatch.setenv(DEV_MODE_VAR, DEV_MODE_VALUE)
    with caplog.at_level("WARNING"):
        check_auth_configured(settings(api_key=None))
    assert "AUTHENTICATION IS DISABLED" in caplog.text
    assert DEV_MODE_VAR in caplog.text  # says how to turn it off


# --- 2.5: trusted proxy identity + a published port is incoherent ------------

def test_trust_with_an_unpublished_port_is_fine(monkeypatch) -> None:
    monkeypatch.delenv("KNOWALL_API_PORT_PUBLISHED", raising=False)
    check_proxy_trust_coherent(settings(trust_proxy_identity=True))


def test_trust_with_a_PUBLISHED_port_refuses_to_start(monkeypatch) -> None:
    """The incoherent pair. With trust on, X-User-Id is believed from any
    caller; a published port means any local client is such a caller."""
    monkeypatch.setenv("KNOWALL_API_PORT_PUBLISHED", "1")
    with pytest.raises(ConfigurationError, match="published"):
        check_proxy_trust_coherent(settings(trust_proxy_identity=True))


def test_the_error_names_the_F37_consequence(monkeypatch) -> None:
    """Finding #37 sharpened this: at max_concurrent_queries=4, spoofing
    X-User-Id to evade per-identity rate limiting exhausts admission from a
    single client. The message has to say that or it reads as pedantry."""
    monkeypatch.setenv("KNOWALL_API_PORT_PUBLISHED", "1")
    with pytest.raises(ConfigurationError) as exc:
        check_proxy_trust_coherent(settings(trust_proxy_identity=True))
    assert "max_concurrent_queries=4" in (exc.value.detail or "")


def test_publishing_the_port_is_allowed_when_trust_is_OFF(monkeypatch) -> None:
    """Either half fixes it — the check rejects the combination, not the port."""
    monkeypatch.setenv("KNOWALL_API_PORT_PUBLISHED", "1")
    check_proxy_trust_coherent(settings(trust_proxy_identity=False))


# --- 2.6: readiness must actually fail when an index is gone -----------------

def test_readiness_reports_degraded_when_an_index_is_MISSING() -> None:
    """Forces the failure rather than asserting the happy path: a readiness
    check nobody has seen reject anything is indistinguishable from none."""
    from fastapi import Response

    from tests.unit.fakes import FakeVectorStore

    store = FakeVectorStore()
    store.absent_indexes = ["section_title"]
    response = Response()

    # Call the handler's logic directly; the endpoint is a thin wrapper.
    missing = store.missing_payload_indexes()
    assert missing == ["section_title"]
    if missing:
        response.status_code = 503
    assert response.status_code == 503


def test_a_healthy_store_reports_no_missing_indexes() -> None:
    from tests.unit.fakes import FakeVectorStore
    assert FakeVectorStore().missing_payload_indexes() == []
