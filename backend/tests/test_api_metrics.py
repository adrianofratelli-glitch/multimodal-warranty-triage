"""Endpoint test for /api/metrics — no Mongo/Anthropic/Voyage dependency, so no mocking needed."""

from fastapi.testclient import TestClient

from main import app


def test_metrics_endpoint_returns_snapshot_shape():
    with TestClient(app) as client:
        resp = client.get("/api/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert "uptime_seconds" in body
    assert "routes" in body
    assert "counters" in body


def test_metrics_endpoint_sets_request_id_header():
    with TestClient(app) as client:
        resp = client.get("/api/metrics")
    assert "x-request-id" in resp.headers
