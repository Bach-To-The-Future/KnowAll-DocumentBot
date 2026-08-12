"""No shipped placeholder may reach a running process, at either entry point.

R1.2. `check_auth_configured` covered exactly ONE of the placeholders
`.env.example` ships — `API_KEY` — and the WORKER ran no configuration checks at
all, so it started normally on the full placeholder set while the API refused.

Two failure directions, both tested here:
  * a credential the guard does not know about ships unchallenged
  * an entry point the guard is not wired into ships unchallenged

The second is the one that actually happened, and it is the reason every test
below runs against both `entry_point="api"` and `entry_point="worker"`.
"""
from __future__ import annotations

import pytest

from core.config import Settings
from core.exceptions import ConfigurationError
from core.startup_checks import (
    CREDENTIAL_FIELDS,
    DEV_MODE_VALUE,
    DEV_MODE_VAR,
    check_no_placeholder_credentials,
    run_all,
)

PLACEHOLDER = "REPLACE_ME_BEFORE_ANY_DEPLOY"

REAL = {
    "api_key": "real-admin-key",
    "api_query_keys": "real-readonly-key",
    "qdrant_api_key": "real-qdrant-key",
    "minio_access_key": "real-minio-user",
    "minio_secret_key": "real-minio-secret",
}


def settings(**overrides):
    return Settings(_env_file=None, **{**REAL, **overrides})


@pytest.mark.parametrize("field,env_name", CREDENTIAL_FIELDS)
@pytest.mark.parametrize("entry_point", ["api", "worker"])
def test_each_credential_is_refused_independently(field, env_name, entry_point) -> None:
    """Every field, on its own, at both entry points.

    Parametrised over CREDENTIAL_FIELDS rather than a hand-written list, so
    adding a credential without a test is not possible.
    """
    with pytest.raises(ConfigurationError) as exc:
        check_no_placeholder_credentials(
            settings(**{field: PLACEHOLDER}), entry_point=entry_point
        )
    assert env_name in exc.value.detail
    assert entry_point in str(exc.value)


@pytest.mark.parametrize("entry_point", ["api", "worker"])
def test_a_fully_replaced_set_starts(entry_point) -> None:
    """The control. Without it, a guard that refused everything would pass."""
    check_no_placeholder_credentials(settings(), entry_point=entry_point)


def test_every_offender_is_reported_not_just_the_first() -> None:
    """An operator who fixes one, restarts, and is told about the next will
    reasonably conclude the guard is broken and look for a way around it."""
    with pytest.raises(ConfigurationError) as exc:
        check_no_placeholder_credentials(
            settings(api_key=PLACEHOLDER, qdrant_api_key=PLACEHOLDER,
                     minio_secret_key=PLACEHOLDER),
            entry_point="api",
        )
    detail = exc.value.detail
    assert "API_KEY" in detail and "QDRANT_API_KEY" in detail
    assert "MINIO_SECRET_KEY" in detail
    assert "3 credential(s)" in str(exc.value)


def test_THE_WORKER_REFUSES_THE_SET_IT_USED_TO_ACCEPT() -> None:
    """The actual defect: the worker started normally on shipped placeholders.

    It holds the same datastore credentials as the API and is the entry point
    that WRITES to the index.
    """
    with pytest.raises(ConfigurationError) as exc:
        run_all(
            settings(qdrant_api_key=PLACEHOLDER, minio_access_key=PLACEHOLDER),
            entry_point="worker",
        )
    assert "worker startup" in str(exc.value)


def test_the_worker_does_not_run_the_api_only_auth_check() -> None:
    """An unset api_key disables HTTP auth, which is meaningless for a process
    that serves no HTTP. The worker must not refuse to start over it."""
    run_all(settings(api_key=None), entry_point="worker")


def test_the_api_still_refuses_an_unset_api_key() -> None:
    with pytest.raises(ConfigurationError):
        run_all(settings(api_key=None), entry_point="api")


@pytest.mark.parametrize("entry_point", ["api", "worker"])
def test_dev_mode_downgrades_to_a_warning_at_both_entry_points(
    entry_point, monkeypatch, caplog
) -> None:
    monkeypatch.setenv(DEV_MODE_VAR, DEV_MODE_VALUE)
    check_no_placeholder_credentials(
        settings(api_key=PLACEHOLDER, qdrant_api_key=PLACEHOLDER),
        entry_point=entry_point,
    )
    assert "INSECURE DEV MODE" in caplog.text
    assert entry_point in caplog.text


def test_minio_credentials_are_covered() -> None:
    """R1.3. These shipped as minio_user/minio_password — functional working
    credentials, published, on the store holding every uploaded document."""
    names = {env for _, env in CREDENTIAL_FIELDS}
    assert "MINIO_ACCESS_KEY" in names
    assert "MINIO_SECRET_KEY" in names
