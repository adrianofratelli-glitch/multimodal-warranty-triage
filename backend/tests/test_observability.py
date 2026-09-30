"""Unit tests for observability.py's Metrics — pure in-memory logic, no network."""

from observability import Metrics


class TestMetrics:
    def test_observe_increments_request_count(self):
        m = Metrics()
        m.observe("/api/lookup", 200, 12.5)
        m.observe("/api/lookup", 200, 7.5)
        snap = m.snapshot()
        assert snap["routes"]["/api/lookup"]["requests"] == 2
        assert snap["routes"]["/api/lookup"]["avg_latency_ms"] == 10.0
        assert snap["routes"]["/api/lookup"]["max_latency_ms"] == 12.5

    def test_5xx_counted_as_error(self):
        m = Metrics()
        m.observe("/api/analisar", 503, 20)
        m.observe("/api/analisar", 200, 5)
        assert m.snapshot()["routes"]["/api/analisar"]["errors_5xx"] == 1

    def test_4xx_not_counted_as_error(self):
        m = Metrics()
        m.observe("/api/lookup", 404, 3)
        assert m.snapshot()["routes"]["/api/lookup"]["errors_5xx"] == 0

    def test_bump_business_counter(self):
        m = Metrics()
        m.bump("analise_created")
        m.bump("analise_created", 2)
        assert m.snapshot()["counters"]["analise_created"] == 3
