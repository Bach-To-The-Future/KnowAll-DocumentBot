"""The admission ceiling must be rejected when it does not fit memory.

R1.1. The shipping config was `max_concurrent_queries=4` against a 3 GiB
container whose settled footprint at concurrency 1 was already 2.99 GiB. A guard
that only compared the ceiling to a generator lookup would have PASSED it, since
4 is a plausible ceiling for some generator. It is the arithmetic against the
real cgroup limit that rejects it.
"""
from __future__ import annotations

import pytest

from core import admission_limits as al
from core.config import Settings
from core.exceptions import ConfigurationError

GIB = 1024 ** 3


def settings(**kw):
    return Settings(_env_file=None, api_key="x", **kw)


@pytest.fixture
def limit(monkeypatch):
    def _set(gib):
        monkeypatch.setattr(al, "container_memory_limit_bytes",
                            lambda: int(gib * GIB))
    return _set


def test_the_model_reproduces_the_measurement() -> None:
    """Predicted concurrency-2 footprint vs what was actually measured.

    The only independent check available on the formula: it was fitted from the
    fixed/first/marginal numbers and must land on the separately measured
    4.876 GiB at n=2.
    """
    p = al.PROFILES["llama3.2:1b"]
    assert p.required_gib(1) == pytest.approx(3.87, abs=0.01)
    assert p.required_gib(2) == pytest.approx(4.876, abs=0.02)


def test_THE_SHIPPED_CONFIG_IS_REJECTED(limit) -> None:
    """4 against 3 GiB — the combination that actually shipped and restarted."""
    limit(3)
    with pytest.raises(ConfigurationError) as e:
        al.check_admission_fits_memory(settings(max_concurrent_queries=4))
    msg = str(e.value)
    assert "does not fit this container's memory limit" in msg


def test_the_error_names_the_ceiling_that_would_fit(limit) -> None:
    """A refusal that does not say what to do instead is half a guard."""
    limit(3)
    with pytest.raises(ConfigurationError) as e:
        al.check_admission_fits_memory(settings(max_concurrent_queries=4))
    assert "supports a ceiling of 0" in e.value.detail or "MAX_CONCURRENT_QUERIES=" in e.value.detail


def test_one_fits_the_raised_limit(limit) -> None:
    limit(5)
    al.check_admission_fits_memory(settings(max_concurrent_queries=1))


def test_two_is_refused_at_five_gib_despite_technically_fitting(limit) -> None:
    """4.876 of 5 GiB is 98%: it fits and it is still wrong.

    3 GiB at 99.6% is what restarted under load. Sizing to the edge one level
    up would reproduce the defect, so the guard requires headroom rather than
    mere arithmetic fit.
    """
    limit(5)
    with pytest.raises(ConfigurationError):
        al.check_admission_fits_memory(settings(max_concurrent_queries=2))


def test_two_fits_once_there_is_genuine_headroom(limit) -> None:
    limit(6)
    al.check_admission_fits_memory(settings(max_concurrent_queries=2))


def test_an_unmeasured_generator_warns_rather_than_guessing(limit, caplog) -> None:
    """qwen3.5:4b has no profile because F37 is retracted.

    Inventing constants for it would reproduce the original defect: a ceiling
    derived from something other than measurement.
    """
    limit(5)
    al.check_admission_fits_memory(settings(ollama_llm_model="qwen3.5:4b",
                                            max_concurrent_queries=99))
    assert "CANNOT be validated" in caplog.text


def test_no_limit_warns_rather_than_passing_silently(monkeypatch, caplog) -> None:
    monkeypatch.setattr(al, "container_memory_limit_bytes", lambda: None)
    al.check_admission_fits_memory(settings(max_concurrent_queries=50))
    assert "no memory limit" in caplog.text


def test_oversubscribed_host_is_shouted_about(monkeypatch, caplog) -> None:
    """15.5 GiB declared against 11.68 GiB available — the state that shipped."""
    monkeypatch.setenv("KNOWALL_DECLARED_MEMORY_GIB", "15.5")
    monkeypatch.setattr(al, "host_memory_bytes", lambda: int(11.68 * GIB))
    al.check_declared_memory_fits_host()
    assert "OVERSUBSCRIBED" in caplog.text


def test_a_host_that_fits_does_not_warn(monkeypatch, caplog) -> None:
    monkeypatch.setenv("KNOWALL_DECLARED_MEMORY_GIB", "11.5")
    monkeypatch.setattr(al, "host_memory_bytes", lambda: int(11.68 * GIB))
    al.check_declared_memory_fits_host()
    assert "OVERSUBSCRIBED" not in caplog.text


def test_ollama_over_allocation_is_flagged(monkeypatch, caplog) -> None:
    """8 GiB for a generator measured at 4 — the second instance of the pattern."""
    monkeypatch.setenv("KNOWALL_OLLAMA_MEMORY_GIB", "8")
    al.check_generator_memory_allocation(settings())
    assert "never adopted" in caplog.text


def test_matching_ollama_allocation_is_silent(monkeypatch, caplog) -> None:
    monkeypatch.setenv("KNOWALL_OLLAMA_MEMORY_GIB", "4")
    al.check_generator_memory_allocation(settings())
    assert "never adopted" not in caplog.text
