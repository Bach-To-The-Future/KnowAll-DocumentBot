from core.telemetry import Telemetry
from tests.unit.fakes import FakeCache


def test_empty_window_reports_zero():
    assert Telemetry(FakeCache()).rolling_stats() == {"n": 0}


def test_rates_and_percentiles():
    telemetry = Telemetry(FakeCache())
    telemetry.record_query({"retrieval_ms": 100.0}, abstained=True, cache_hit=False)
    telemetry.record_query({"retrieval_ms": 300.0}, abstained=False, cache_hit=True)

    stats = telemetry.rolling_stats()
    assert stats["n"] == 2
    assert stats["abstention_rate"] == 0.5
    assert stats["cache_hit_rate"] == 0.5
    assert stats["retrieval_ms"]["p50"] in (100.0, 300.0)
    assert stats["retrieval_ms"]["p95"] == 300.0


def test_window_is_bounded():
    telemetry = Telemetry(FakeCache(), window=3)
    for _ in range(10):
        telemetry.record_query({}, abstained=False, cache_hit=False)
    assert telemetry.rolling_stats()["n"] == 3


def test_poisoned_sample_is_skipped():
    cache = FakeCache()
    telemetry = Telemetry(cache)
    telemetry.record_query({}, abstained=False, cache_hit=False)
    cache.lists["telemetry:queries"].append("{corrupt")
    assert telemetry.rolling_stats()["n"] == 1  # must not raise
