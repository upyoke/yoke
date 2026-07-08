"""The server advertises its engine version as an API response header.

The version-handshake header rides every response the app middleware
touches — the function-call route in particular, including auth denials,
so a client can detect skew before it even authenticates. A source run
without dist metadata advertises nothing and clients stay silent.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from yoke_contracts.engine_version import ENGINE_VERSION_HEADER


def _client_with_engine_version(monkeypatch, value: str) -> TestClient:
    from yoke_core.api import app_factory

    monkeypatch.setattr(
        app_factory, "advertised_engine_version",
        lambda *, build="": value,
    )
    return TestClient(app_factory.create_app())


def test_functions_call_response_carries_engine_version_header(monkeypatch):
    client = _client_with_engine_version(monkeypatch, "9.9.9")
    # Unauthenticated: the middleware stamps the header on the denial too,
    # so skew is detectable even before credentials are set up.
    resp = client.post("/v1/functions/call", json={})
    assert resp.status_code == 401
    assert resp.headers[ENGINE_VERSION_HEADER] == "9.9.9"


def test_health_response_carries_engine_version_header(monkeypatch):
    client = _client_with_engine_version(monkeypatch, "9.9.9")
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.headers[ENGINE_VERSION_HEADER] == "9.9.9"


def test_source_run_omits_engine_version_header(monkeypatch):
    client = _client_with_engine_version(monkeypatch, "")
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert ENGINE_VERSION_HEADER not in resp.headers


def test_image_fallback_metadata_omits_engine_version_header(monkeypatch):
    from yoke_core.api import app_factory
    from yoke_contracts import engine_version as ev

    monkeypatch.setenv("YOKE_BUILD_SHA", "abc123def456")
    monkeypatch.setattr(
        ev, "installed_engine_version",
        lambda: ev.UNRESOLVED_SCM_FALLBACK_VERSION,
    )
    client = TestClient(app_factory.create_app())
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert ENGINE_VERSION_HEADER not in resp.headers
    assert resp.json()["engine_version"] == ""
    assert resp.json()["build"] == "abc123def456"
