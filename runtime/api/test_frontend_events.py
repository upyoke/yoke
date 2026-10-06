"""Anonymous workbench requests exercise the real Postgres collector sink."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from runtime.api.fixtures import pg_testdb
from yoke_core.api import app_factory
from yoke_core.api.routes import frontend_events
from yoke_core.domain import db_helpers, events_writes
from yoke_core.domain.auth_schema import create_auth_tables
from yoke_core.domain.events_schema import ensure_event_schema
from yoke_core.domain.org_schema import seed_default_org
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_identity_tables,
)
from yoke_core.domain.schema_init_tables import create_core_tables

ORIGIN = "https://workbench.example.test"


def test_shipped_runtime_matches_installed_pack():
    from yoke_core.tools.build_frontend_events import outputs

    root = Path(__file__).resolve().parents[2]
    for path, expected in outputs(root).items():
        assert path.read_text() == expected, f"frontend_events_build_stale: {path}"


@pytest.fixture
def database(monkeypatch):
    name = pg_testdb.create_test_database()

    def connect(*args, **kwargs):
        return pg_testdb.connect_test_database(name)

    with connect() as conn:
        create_core_tables(conn)
        create_actor_identity_tables(conn)
        create_auth_tables(conn)
        seed_default_org(conn)
        ensure_event_schema(conn)
        conn.commit()
    monkeypatch.setattr(db_helpers, "connect", connect)
    monkeypatch.setattr(events_writes, "connect", connect)
    yield connect
    pg_testdb.drop_test_database(name)


@pytest.fixture
def client(database):
    return TestClient(app_factory.create_app(), base_url=ORIGIN)


def headers(client, origin=ORIGIN):
    config = client.get("/api/events/config")
    assert config.status_code == 200
    return {"Origin": origin, "X-Events-Key": config.json()["publishableKey"]}


def event():
    return {
        "event_id": str(uuid4()),
        "event_name": "PageViewed",
        "event_kind": "analytics",
        "event_type": "page_view",
        "event_time": "2026-01-01T00:00:00Z",
        "session_id": str(uuid4()),
        "source_type": "frontend",
        "page_url": ORIGIN + "/items?token=door-secret&utm_source=email#private",
        "referrer": "https://search.test/?token=private",
        "actor_id": 999999,
        "org_id": "forged",
        "project_id": 999999,
        "context": {"project_id": 999999, "detail": {"project_id": 999999}},
    }


def test_anonymous_sink_sanitizes_deduplicates_and_stamps_its_own_identity(
    client, database
):
    payload, admitted = event(), headers(client)
    for _ in range(2):
        response = client.post(
            "/api/events", json={"events": [payload]}, headers=admitted
        )
        assert response.status_code == 200
        assert response.json() == {"accepted": 1}
    with database() as conn:
        rows = conn.execute(
            "SELECT actor_id, project_id, org_id, envelope FROM events WHERE event_id=%s",
            (payload["event_id"],),
        ).fetchall()
        assert len(rows) == 1
        actor_id, project_id, org_id, raw = rows[0]
        assert actor_id is None and project_id is None and org_id != "forged"
        stored = json.loads(raw) if isinstance(raw, str) else raw
        assert stored["page_url"] == ORIGIN + "/items?utm_source=email"
        assert "private" not in stored["referrer"]
        assert stored["actor_id"] is None
        assert "project_id" not in stored
        assert "project_id" not in stored["context"]
        assert "project_id" not in stored["context"]["detail"]
        assert stored["session_id"] == "browser:" + payload["session_id"]


@pytest.mark.parametrize(
    "origin,key,reason",
    [
        ("https://attacker.test", None, "origin_not_allowed"),
        (ORIGIN, "incorrect", "publishable_key_invalid"),
        ("", None, "origin_not_allowed"),
    ],
)
def test_collector_refuses_bad_origin_and_key_by_name(client, origin, key, reason):
    admitted = headers(client, origin)
    if key is not None:
        admitted["X-Events-Key"] = key
    response = client.post("/api/events", json={"events": [event()]}, headers=admitted)
    assert response.status_code in (401, 403)
    assert response.json()["error"] == reason
    assert response.json()["recovery"]


def test_anonymous_route_cannot_write_backend_events_or_malformed_envelopes(client):
    admitted = headers(client)
    for changed in (
        {"source_type": "backend"},
        {"event_kind": "security"},
        {"source_type": None},
        {"page_url": {}},
        {"event_id": "not-a-uuid"},
    ):
        response = client.post(
            "/api/events", json={"events": [{**event(), **changed}]}, headers=admitted
        )
        assert response.status_code == 400
        assert response.json()["error"] == "envelope_invalid"


def test_collector_failure_and_rate_limit_never_report_acceptance(client, monkeypatch):
    admitted = headers(client)
    monkeypatch.setattr(frontend_events, "admit_client", lambda *args, **kwargs: 7)
    limited = client.post("/api/events", json={"events": [event()]}, headers=admitted)
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "7"
    assert limited.json()["error"] == "rate_limited"
    monkeypatch.setattr(frontend_events, "admit_client", lambda *args, **kwargs: 0)

    def unavailable(*args, **kwargs):
        raise RuntimeError("sink unavailable")

    monkeypatch.setattr(frontend_events, "write_frontend_events", unavailable)
    failed = client.post("/api/events", json={"events": [event()]}, headers=admitted)
    assert failed.status_code == 503
    assert failed.json()["error"] == "collector_unavailable"
    assert "accepted" not in failed.json()


def test_attribution_requires_consent_uses_signed_httponly_cookie_and_revokes(client):
    admitted = headers(client)
    capture = {
        "url": ORIGIN + "/?utm_source=newsletter&utm_medium=email",
        "referrer": "",
    }
    denied = client.post("/api/events/attribution", json=capture, headers=admitted)
    assert denied.status_code == 403 and denied.json()["error"] == "consent_required"
    first = client.post(
        "/api/events/attribution", json={**capture, "consent": True}, headers=admitted
    )
    assert first.status_code == 200
    assert (
        "HttpOnly" in first.headers["Set-Cookie"]
        and "; Secure" in first.headers["Set-Cookie"]
    )
    record = first.json()
    later = client.post(
        "/api/events/attribution",
        json={"url": ORIGIN + "/items", "referrer": ORIGIN, "consent": True},
        headers=admitted,
    )
    assert later.json() == record
    revoked = client.delete("/api/events/attribution", headers=admitted)
    assert revoked.status_code == 200
    assert "Max-Age=0" in revoked.headers["Set-Cookie"]


def test_local_collector_has_no_bearer_requirement_and_keeps_http_cookie(
    database, monkeypatch
):
    from yoke_core.ui import server

    monkeypatch.setattr(server, "serving_connection", lambda: ("validation", None))
    local = TestClient(
        server.create_ui_app("door", port=8689), base_url="http://127.0.0.1:8689"
    )
    admitted = headers(local, "http://127.0.0.1:8689")
    response = local.post(
        "/api/events/attribution",
        headers=admitted,
        json={
            "url": "http://127.0.0.1:8689/?token=door",
            "referrer": "",
            "consent": True,
        },
    )
    assert response.status_code == 200
    assert "events_attribution_8689=" in response.headers["Set-Cookie"]
    assert "; Secure" not in response.headers["Set-Cookie"]
    assert "HttpOnly" in response.headers["Set-Cookie"]
    payload = {**event(), "page_url": "http://127.0.0.1:8689/?token=door"}
    assert (
        local.post(
            "/api/events", json={"events": [payload]}, headers=admitted
        ).status_code
        == 200
    )
