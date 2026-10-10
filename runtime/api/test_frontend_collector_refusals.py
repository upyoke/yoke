"""Collector refusals leave bounded server events; accepted events carry receipt time."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from runtime.api import test_frontend_events as collector_tests
from yoke_core.api import frontend_events_config
from yoke_core.api.routes import frontend_events
from yoke_core.domain import frontend_collector_refusals
from yoke_core.domain.frontend_collector_refusals import REFUSAL_EVENT, record_refusal

database = collector_tests.database
client = collector_tests.client
headers = collector_tests.headers
event = collector_tests.event
ORIGIN = collector_tests.ORIGIN


@pytest.fixture(autouse=True)
def fresh_memo():
    frontend_collector_refusals._recorded.clear()
    yield
    frontend_collector_refusals._recorded.clear()


def refusals(database):
    with database() as conn:
        rows = conn.execute(
            "SELECT source_type, event_kind, severity, event_outcome, envelope "
            "FROM events WHERE event_name=%s ORDER BY created_at",
            (REFUSAL_EVENT,),
        ).fetchall()
    return [
        (
            source,
            kind,
            severity,
            outcome,
            json.loads(raw) if isinstance(raw, str) else raw,
        )
        for source, kind, severity, outcome, raw in rows
    ]


def refused(client, path, admitted, monkeypatch, reason):
    if reason == "rate_limited":
        monkeypatch.setattr(frontend_events, "admit_client", lambda *a, **k: 7)
    if reason == "payload_too_large":
        return client.post(
            path,
            content=b'{"events": "' + b"x" * 600_000 + b'"}',
            headers={**admitted, "Content-Type": "application/json"},
        )
    if path == frontend_events_config.REDEEM_PATH:
        return client.post(path, json={"token": "forged"}, headers=admitted)
    return client.post(
        path, json={"events": [{**event(), "event_id": "x"}]}, headers=admitted
    )


@pytest.mark.parametrize(
    "path, change, reason, status",
    [
        (
            frontend_events_config.EVENTS_PATH,
            {"Origin": "https://attacker.test"},
            "origin_not_allowed",
            403,
        ),
        (
            frontend_events_config.EVENTS_PATH,
            {"X-Events-Key": "incorrect"},
            "publishable_key_invalid",
            401,
        ),
        (frontend_events_config.EVENTS_PATH, {}, "rate_limited", 429),
        (frontend_events_config.EVENTS_PATH, {}, "payload_too_large", 413),
        (frontend_events_config.EVENTS_PATH, {}, "envelope_invalid", 400),
        (frontend_events_config.REDEEM_PATH, {}, "attribution_handoff_invalid", 400),
    ],
)
def test_each_refusal_records_one_named_diagnostic_event(
    client, database, monkeypatch, path, change, reason, status
):
    admitted = {**headers(client), **change}
    response = refused(client, path, admitted, monkeypatch, reason)
    assert response.status_code == status
    assert response.json()["error"] == reason
    [(source, kind, severity, outcome, envelope)] = refusals(database)
    assert (source, kind, severity, outcome) == ("backend", "system", "WARN", reason)
    detail = envelope["context"]["detail"]
    assert detail["reason"] == reason and detail["status"] == status
    assert detail["route"] == path
    assert detail["origin"] == admitted["Origin"]
    assert detail["host"] == ORIGIN.removeprefix("https://")
    stored = json.dumps(envelope)
    assert admitted["X-Events-Key"] not in stored and "xxxx" not in stored


def test_refusal_flood_writes_one_row_per_kind_per_minute(client, database):
    hostile = {**headers(client), "Origin": "https://attacker.test"}
    for index in range(40):
        hostile["Origin"] = f"https://attacker-{index}.test"
        response = client.post(
            "/api/events", json={"events": [event()]}, headers=hostile
        )
        assert response.status_code == 403
    assert len(refusals(database)) == 1
    later = datetime.now(timezone.utc) + timedelta(minutes=2)
    frontend_collector_refusals._recorded.clear()  # a second process
    for _ in range(2):
        record_refusal(
            reason="origin_not_allowed",
            status=403,
            route="/api/events",
            origin="https://attacker.test",
            host="workbench.example.test",
            now=int(datetime.now(timezone.utc).timestamp()),
        )
    assert len(refusals(database)) == 1
    record_refusal(
        reason="origin_not_allowed",
        status=403,
        route="/api/events",
        origin="https://a.test",
        host="h",
        now=int(later.timestamp()),
    )
    assert len(refusals(database)) == 2


def test_recording_failure_keeps_the_named_refusal(client, database, monkeypatch):
    def broken(**kwargs):
        raise RuntimeError("events table unavailable")

    monkeypatch.setattr(frontend_collector_refusals, "cmd_insert", broken)
    hostile = {**headers(client), "Origin": "https://attacker.test"}
    response = client.post("/api/events", json={"events": [event()]}, headers=hostile)
    assert response.status_code == 403
    assert response.json()["error"] == "origin_not_allowed"


def stored(database, event_id):
    with database() as conn:
        created, flags, raw = conn.execute(
            "SELECT created_at, anomaly_flags, envelope FROM events WHERE event_id=%s",
            (event_id,),
        ).fetchone()
    return created, flags, json.loads(raw) if isinstance(raw, str) else raw


def test_accepted_events_are_ordered_by_server_receipt_time(client, database):
    now = datetime.now(timezone.utc)
    current = {**event(), "event_time": now.strftime("%Y-%m-%dT%H:%M:%S.000Z")}
    forged = {**event(), "received_at": "1999-01-01T00:00:00Z"}
    response = client.post(
        "/api/events", json={"events": [current, forged]}, headers=headers(client)
    )
    assert response.json() == {"accepted": 2}
    created, flags, envelope = stored(database, current["event_id"])
    assert flags is None and abs(envelope["client_time_offset_seconds"]) <= 5
    assert envelope["event_time"] == current["event_time"]
    created, flags, envelope = stored(database, forged["event_id"])
    assert flags == "client_time_skew"
    assert envelope["event_time"] == "2026-01-01T00:00:00Z"
    received = datetime.fromisoformat(envelope["received_at"].replace("Z", "+00:00"))
    assert abs((received - now).total_seconds()) <= 5
    assert created == envelope["received_at"]
    assert envelope["client_time_offset_seconds"] < -300
