"""Configuration coherence checks, run at startup.

A comment does not survive the next person editing `docker-compose.yml`. These
do — each one fails or warns loudly at boot, at the moment the incoherent
combination is introduced rather than at the moment it is exploited.

Phases 2.5 and 2.7.
"""
from __future__ import annotations

import logging
import os

from core.admission_limits import (
    check_admission_fits_memory,
    check_declared_memory_fits_host,
    check_generator_memory_allocation,
)
from core.config import Settings
from core.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

# Deliberately awkward: a named variable that must be set to an exact,
# self-describing string, and that logs on EVERY startup. A quiet boolean is
# the thing that gets set in production and forgotten.
DEV_MODE_VAR = "KNOWALL_INSECURE_DEV_MODE"
DEV_MODE_VALUE = "i-understand-this-disables-authentication"

# R1.4. Replaces KNOWALL_API_PORT_PUBLISHED, which nothing ever set: it appeared
# once outside this module, in a docker-compose COMMENT, so the guard read a
# declaration that did not exist and passed on a genuinely published port.
# This one is REQUIRED when trust is on, and its absence fails closed.
BINDING_VAR = "KNOWALL_API_PORT_BINDING"

# Shipped placeholders. These must not start a server: they are published in
# the repository, so anyone can read them.
KNOWN_PLACEHOLDERS = frozenset({
    "REPLACE_ME",
    "REPLACE_ME_BEFORE_ANY_DEPLOY",
})

# Every credential-shaped setting the BACKEND can see, with the env var an
# operator would edit. SESSION_SECRET and AUTH_PASSWORD are deliberately absent:
# they exist only in the web tier, which enforces them itself
# (frontend/src/lib/startup-checks.ts).
#
# R1.2. This list exists because check_auth_configured covered exactly ONE of
# the six placeholders `.env.example` ships, and the worker — the second entry
# point — ran no check at all. A guard covering one of two entry points is a
# guard with a hole, and five of six placeholders started the stack unchallenged.
CREDENTIAL_FIELDS: tuple[tuple[str, str], ...] = (
    ("api_key", "API_KEY"),
    ("api_query_keys", "API_QUERY_KEYS"),
    ("qdrant_api_key", "QDRANT_API_KEY"),
    ("minio_access_key", "MINIO_ACCESS_KEY"),
    ("minio_secret_key", "MINIO_SECRET_KEY"),
)


def check_no_placeholder_credentials(settings: Settings, *, entry_point: str) -> None:
    """No shipped placeholder may reach a running process, at ANY entry point.

    Reports EVERY offender rather than the first: an operator who fixes one and
    restarts, only to be told about the next, will reasonably conclude the guard
    is broken and look for a way around it.
    """
    offenders = []
    for field, env_name in CREDENTIAL_FIELDS:
        value = getattr(settings, field, None)
        if isinstance(value, str) and value.strip() in KNOWN_PLACEHOLDERS:
            offenders.append(f"{env_name}={value.strip()!r}")

    if not offenders:
        return

    listed = "\n  ".join(offenders)
    if _dev_mode_enabled():
        logger.warning(
            f"INSECURE DEV MODE: {len(offenders)} shipped placeholder(s) in use at "
            f"{entry_point} startup:\n  {listed}"
        )
        return

    raise ConfigurationError(
        f"Refusing to start: {len(offenders)} credential(s) are still the shipped "
        f"placeholder at {entry_point} startup.",
        detail=(
            f"These are published in the repository, so anyone can read them:\n"
            f"  {listed}\n"
            f"Replace every one in .env. If this is genuinely a local development "
            f"run, set {DEV_MODE_VAR}={DEV_MODE_VALUE}."
        ),
    )


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

    The admission gate sharpens this. The ceiling is small — measured at 1 for
    the shipped generator (core/admission_limits.py) — so spoofing `X-User-Id`
    to evade per-identity rate limiting is cheap enough to exhaust admission
    from a single client: the blast radius goes from "unfair share" to "denial
    of service". The lower the ceiling, the cheaper the attack, which is why
    this check quotes the configured value rather than a fixed number.
    """
    if not settings.trust_proxy_identity:
        return

    binding = os.getenv(BINDING_VAR, "").strip().lower()

    if binding in ("published", "public", "0.0.0.0"):
        raise ConfigurationError(
            "Refusing to start: TRUST_PROXY_IDENTITY is on while the API port is "
            "published to the host.",
            detail=(
                f"With trust on, X-User-Id and X-Forwarded-For are believed from any "
                f"caller, which is only safe when the authenticated proxy is the sole "
                f"ingress. A published port means a local client can name itself and "
                f"evade per-identity rate limiting — and with "
                f"max_concurrent_queries={settings.max_concurrent_queries} that is "
                f"enough to exhaust admission from one client. "
                f"Either bind the port to 127.0.0.1 and set {BINDING_VAR}=loopback, "
                f"or set TRUST_PROXY_IDENTITY=false."
            ),
        )

    if binding in ("loopback", "127.0.0.1", "none", "unpublished"):
        return

    # R1.4. FAIL CLOSED. The previous version returned early on an unset
    # variable, so the guard passed on a genuinely published port — it enforced
    # an operator's declaration and nothing set the declaration. The variable
    # appeared exactly once outside this file, in a compose COMMENT.
    raise ConfigurationError(
        f"Refusing to start: TRUST_PROXY_IDENTITY is on but {BINDING_VAR} is not "
        f"set, so the API's exposure cannot be established.",
        detail=(
            f"This cannot be detected from inside the container, and that was "
            f"MEASURED rather than assumed: with the host mapping "
            f"127.0.0.1:8000->8000 and with 0.0.0.0:8000->8000, the container's "
            f"own view is byte-identical (it listens on 0.0.0.0:8000 in its own "
            f"network namespace either way). Host port publishing happens outside "
            f"that namespace. Reading the Docker socket could answer it, but "
            f"mounting the socket to check a config flag trades a much larger "
            f"privilege for a much smaller one.\n"
            f"So the declaration is REQUIRED rather than optional, and its absence "
            f"is treated as unsafe rather than as safe. Set "
            f"{BINDING_VAR}=loopback next to a 127.0.0.1 port mapping, "
            f"{BINDING_VAR}=published otherwise, or set TRUST_PROXY_IDENTITY=false "
            f"and stop believing caller-supplied identity headers."
        ),
    )


def run_all(settings: Settings, *, entry_point: str = "api") -> None:
    """`entry_point` names the process, because the worker runs a subset.

    The worker serves no HTTP, so it has no API key to check and no port to be
    incoherent about — but it DOES hold datastore credentials, and it started
    normally on the shipped placeholder set until R1.2.
    """
    check_no_placeholder_credentials(settings, entry_point=entry_point)
    if entry_point != "api":
        return
    check_auth_configured(settings)
    check_proxy_trust_coherent(settings)
    # R1.1 — the admission ceiling, the generator's memory allocation and the
    # host total. Prose held the first two couplings and prose failed twice.
    check_admission_fits_memory(settings)
    check_generator_memory_allocation(settings)
    check_declared_memory_fits_host()
