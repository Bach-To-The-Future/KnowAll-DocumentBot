"""Configuration coherence checks, run at startup.

A comment does not survive the next person editing `docker-compose.yml`. These
do — each one fails or warns loudly at boot, at the moment the incoherent
combination is introduced rather than at the moment it is exploited.

Phases 2.5 and 2.7.
"""
from __future__ import annotations

import logging
import os

from core.config import Settings
from core.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

# Deliberately awkward: a named variable that must be set to an exact,
# self-describing string, and that logs on EVERY startup. A quiet boolean is
# the thing that gets set in production and forgotten.
DEV_MODE_VAR = "KNOWALL_INSECURE_DEV_MODE"
DEV_MODE_VALUE = "i-understand-this-disables-authentication"

# Shipped placeholders. These must not start a server: they are published in
# the repository, so anyone can read them.
KNOWN_PLACEHOLDERS = frozenset({
    "REPLACE_ME",
    "REPLACE_ME_BEFORE_ANY_DEPLOY",
})


def _dev_mode_enabled() -> bool:
    return os.getenv(DEV_MODE_VAR, "") == DEV_MODE_VALUE


def check_auth_configured(settings: Settings) -> None:
    """Phase 2.7. An unset `api_key` disables authentication entirely.

    That is a legitimate local-development state and an unacceptable deployed
    one, and nothing previously distinguished them — the default simply left
    the API open.
    """
    if settings.api_key and settings.api_key not in KNOWN_PLACEHOLDERS:
        return

    reason = ("API_KEY is not set" if not settings.api_key
              else f"API_KEY is still the shipped placeholder {settings.api_key!r}")

    if _dev_mode_enabled():
        logger.warning(
            "=" * 72 + "\n"
            f"  INSECURE DEV MODE: {reason}, so AUTHENTICATION IS DISABLED.\n"
            f"  Every endpoint is reachable without a credential.\n"
            f"  This is on because {DEV_MODE_VAR} is set. Unset it to fail closed.\n"
            + "=" * 72
        )
        return

    raise ConfigurationError(
        f"Refusing to start: {reason}, which disables authentication.",
        detail=(
            f"Set API_KEY to a real secret. If this is genuinely a local "
            f"development run, set {DEV_MODE_VAR}={DEV_MODE_VALUE} — it is "
            f"deliberately verbose so it is not set in production by accident, "
            f"and it logs a banner on every startup so it is not forgotten."
        ),
    )


def check_proxy_trust_coherent(settings: Settings) -> None:
    """Phase 2.5. `trust_proxy_identity` and a published port are incoherent.

    With trust on, the API believes `X-User-Id` and `X-Forwarded-For` from any
    caller. That is only safe when the ONLY route to the API is the
    authenticated Next.js tier. If the container publishes 8000 to the host,
    any local client reaches it directly and can name itself.

    Finding #37 sharpened this. With `max_concurrent_queries` now 4, spoofing
    `X-User-Id` to evade per-identity rate limiting is cheap enough to exhaust
    the admission gate from a single client — the blast radius went from
    "unfair share" to "denial of service".
    """
    if not settings.trust_proxy_identity:
        return

    published = os.getenv("KNOWALL_API_PORT_PUBLISHED", "").strip().lower()
    if published in ("", "0", "false", "no"):
        return

    raise ConfigurationError(
        "Refusing to start: TRUST_PROXY_IDENTITY is on while the API port is "
        "published to the host.",
        detail=(
            f"With trust on, X-User-Id and X-Forwarded-For are believed from any "
            f"caller, which is only safe when the authenticated proxy is the sole "
            f"ingress. A published port means a local client can name itself and "
            f"evade per-identity rate limiting — and with "
            f"max_concurrent_queries={settings.max_concurrent_queries} (finding "
            f"#37) that is enough to exhaust admission from one client. "
            f"Either unpublish the port / bind it to 127.0.0.1, or set "
            f"TRUST_PROXY_IDENTITY=false."
        ),
    )


def run_all(settings: Settings) -> None:
    check_auth_configured(settings)
    check_proxy_trust_coherent(settings)
