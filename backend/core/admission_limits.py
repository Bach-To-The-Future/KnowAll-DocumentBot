"""Does the configured admission ceiling actually fit in this container?

WHY THIS EXISTS

`max_concurrent_queries` was 4 in `.env.example` and 20 in the handoff's prose,
and neither number was derived from anything that binds. Finding #37 sized the
ceiling against `llm_read_timeout` alone — it asked how many concurrent requests
fit inside the timeout, and never asked what ELSE could run out first. Memory
runs out first, and at concurrency 1.

F37 IS RETRACTED, NOT CORRECTED. The derivation was wrong, so every value it
produced is unfounded: the 4 that shipped, the 8-request crossing, and the 6–7
figure derived from it. See docs/FINAL_AUDIT.md.

The rule this encodes: before setting a limit, enumerate what could bind, then
measure which binds first.

WHAT IS MEASURED (llama3.2:1b, 376-point corpus, answerable questions,
answer-cache defeated, api container at a 5 GiB cgroup limit)

    fixed resident, no query ever served      1.62 GiB
    settled after 1 concurrent query          3.872 GiB
    settled after 2 concurrent queries        4.876 GiB
    marginal cost of one more concurrent      1.004 GiB

    => required(n) = 1.62 + 2.25 + (n-1) * 1.004

    n=1  3.87 GiB     n=2  4.88 GiB     n=3  5.88 GiB     n=4  6.89 GiB

The model reproduces the measurement at n=2 (predicted 4.88, measured 4.876),
which is the only independent check available for it.

A TRAP WORTH RECORDING. The first attempt measured this against the OLD 3 GiB
limit and concluded memory "plateaus at 2.99 GiB — allocator arenas, not a
leak". That convergence was an ARTIFACT OF THE CEILING: pressed against 3 GiB,
the allocator had to reuse rather than expand. Given 5 GiB it climbed to 3.872
and converged there instead. A measurement taken under the constraint it is
meant to inform will describe the constraint, not the workload.

Memory does not return to baseline after a query — it converges and stays. So
these are steady-state numbers for a warm container, which is the state any
container serving traffic is in.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from core.config import Settings
from core.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

GIB = 1024 ** 3

# Leave real headroom rather than sizing to the edge. 3 GiB was 99.6% consumed
# at concurrency 1 and the container restarted under load; 5 GiB at concurrency
# 2 is 97.5%, which is the same trap one size up. A ceiling that only fits when
# nothing else happens is not a ceiling.
SAFE_UTILISATION = 0.90


@dataclass(frozen=True)
class GeneratorProfile:
    """Measured memory behaviour of the api container for one generator."""
    fixed_resident_gib: float
    first_request_gib: float
    marginal_request_gib: float
    ollama_limit_gib: float
    measured_on: str

    def required_gib(self, concurrency: int) -> float:
        if concurrency <= 0:
            return self.fixed_resident_gib
        return (self.fixed_resident_gib
                + self.first_request_gib
                + (concurrency - 1) * self.marginal_request_gib)


# ONLY generators with MEASURED constants appear here. qwen3.5:4b is deliberately
# absent: its numbers came from F37, which is retracted, and re-deriving them
# means re-running the measurement rather than copying a figure forward.
PROFILES: dict[str, GeneratorProfile] = {
    "llama3.2:1b": GeneratorProfile(
        fixed_resident_gib=1.62,
        first_request_gib=2.25,
        marginal_request_gib=1.004,
        ollama_limit_gib=4.0,
        measured_on="2026-08-12, 376-point corpus, answerable questions, cache defeated",
    ),
}


def container_memory_limit_bytes() -> int | None:
    """This container's own cgroup limit, or None if unlimited/unreadable."""
    for path in ("/sys/fs/cgroup/memory.max",                    # cgroup v2
                 "/sys/fs/cgroup/memory/memory.limit_in_bytes"):  # cgroup v1
        try:
            raw = Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if raw == "max":
            return None
        try:
            value = int(raw)
        except ValueError:
            continue
        # cgroup v1 reports a sentinel near 2^63 when unlimited.
        return None if value >= 2 ** 62 else value
    return None


def host_memory_bytes() -> int | None:
    """Total host memory. Inside Docker, /proc/meminfo is the HOST's."""
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def check_admission_fits_memory(settings: Settings) -> None:
    """Phase R1.1. The ceiling must fit the container, not just the timeout.

    Three inputs, not one: the configured generator selects the measured
    constants, the cgroup supplies the real limit, and the per-request delta
    turns the ceiling into a number of bytes. A generator lookup alone would
    have PASSED the shipping config, because 4 is a plausible ceiling for some
    generator — it is the arithmetic that rejects it.
    """
    profile = PROFILES.get(settings.llm_model)
    if profile is None:
        logger.warning(
            f"No measured memory profile for generator '{settings.llm_model}', so "
            f"max_concurrent_queries={settings.max_concurrent_queries} CANNOT be "
            f"validated. Re-measure with scripts/measure_admission.py before "
            f"trusting it. An unvalidated ceiling is how 4 shipped against a "
            f"generator it was never measured for."
        )
        return

    limit = container_memory_limit_bytes()
    if limit is None:
        logger.warning(
            "This container has no memory limit, so the admission ceiling cannot "
            "be checked against one. In production, set one."
        )
        return

    limit_gib = limit / GIB
    required = profile.required_gib(settings.max_concurrent_queries)
    budget = limit_gib * SAFE_UTILISATION

    if required <= budget:
        logger.info(
            f"admission ceiling {settings.max_concurrent_queries} needs "
            f"~{required:.2f} GiB of {limit_gib:.2f} GiB "
            f"({required / limit_gib:.0%}) for '{settings.llm_model}'."
        )
        return

    fits = 0
    while profile.required_gib(fits + 1) <= budget:
        fits += 1

    raise ConfigurationError(
        f"Refusing to start: max_concurrent_queries={settings.max_concurrent_queries} "
        f"does not fit this container's memory limit.",
        detail=(
            f"Generator '{settings.llm_model}' measured at "
            f"{profile.fixed_resident_gib:.2f} GiB resident, "
            f"+{profile.first_request_gib:.2f} GiB for the first concurrent query and "
            f"+{profile.marginal_request_gib:.2f} GiB for each additional one "
            f"({profile.measured_on}). A ceiling of "
            f"{settings.max_concurrent_queries} therefore needs ~{required:.2f} GiB, "
            f"against a limit of {limit_gib:.2f} GiB "
            f"(usable {budget:.2f} GiB at {SAFE_UTILISATION:.0%}). "
            f"This limit supports a ceiling of {fits}. "
            f"Either set MAX_CONCURRENT_QUERIES={fits}, or raise the api "
            f"container's memory limit — and check the host total first, because "
            f"the declared limits already exceeded available memory once."
        ),
    )


def check_generator_memory_allocation(settings: Settings) -> None:
    """The ollama limit must match the generator too.

    8 GiB was derived for qwen3.5:4b and shipped with llama3.2:1b — the same
    pattern as max_concurrent_queries=4: a number correct for a candidate,
    applied to an incumbent it does not describe. Prose recorded the coupling
    and prose did not hold it.
    """
    profile = PROFILES.get(settings.llm_model)
    declared = os.getenv("KNOWALL_OLLAMA_MEMORY_GIB", "").strip()
    if profile is None or not declared:
        return
    try:
        declared_gib = float(declared)
    except ValueError:
        logger.warning(f"KNOWALL_OLLAMA_MEMORY_GIB={declared!r} is not a number.")
        return

    if abs(declared_gib - profile.ollama_limit_gib) > 0.01:
        logger.warning(
            f"ollama is allocated {declared_gib:.1f} GiB but the measured "
            f"requirement for generator '{settings.llm_model}' is "
            f"{profile.ollama_limit_gib:.1f} GiB. Over-allocation is not free: it "
            f"is counted against the host total, and an 8 GiB allocation sized for "
            f"a generator that was never adopted is what pushed declared memory "
            f"above available memory."
        )


def check_declared_memory_fits_host() -> None:
    """Declared limits summing above available memory is a condition that expires.

    15.5 GiB was declared against an 11.68 GiB host and it worked — because
    nothing approached its limit. The moment one container did, another had
    nowhere to go. Silent until it isn't.
    """
    declared = os.getenv("KNOWALL_DECLARED_MEMORY_GIB", "").strip()
    if not declared:
        return
    try:
        declared_gib = float(declared)
    except ValueError:
        logger.warning(f"KNOWALL_DECLARED_MEMORY_GIB={declared!r} is not a number.")
        return

    host = host_memory_bytes()
    if host is None:
        return
    host_gib = host / GIB

    if declared_gib > host_gib:
        logger.warning(
            "=" * 72 + "\n"
            f"  OVERSUBSCRIBED: compose declares {declared_gib:.1f} GiB of memory "
            f"limits against {host_gib:.1f} GiB available.\n"
            f"  This works only while no container approaches its own limit, and "
            f"nothing reports when that stops being true.\n"
            + "=" * 72
        )
    else:
        logger.info(
            f"declared memory {declared_gib:.1f} GiB fits the "
            f"{host_gib:.1f} GiB host."
        )
