"""HTTP request-id propagation tests for the Yoke API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from yoke_core.api.main import app


def test_health_echoes_http_request_id() -> None:
    client = TestClient(app)
    try:
        resp = client.get(
            "/v1/health",
            headers={"x-request-id": "req-health"},
        )
    finally:
        client.close()
    assert resp.status_code == 200
    assert resp.headers["x-request-id"] == "req-health"


def test_auth_rejection_still_returns_http_request_id() -> None:
    client = TestClient(app)
    try:
        resp = client.get(
            "/v1/functions/registry",
            headers={"x-request-id": "req-denied"},
        )
    finally:
        client.close()
    assert resp.status_code == 401
    assert resp.headers["x-request-id"] == "req-denied"
