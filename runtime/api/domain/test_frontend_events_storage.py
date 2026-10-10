"""Collector identity and rate admission survive process-local state loss."""

from datetime import datetime, timedelta, timezone

import json
import pytest

from runtime.api import test_frontend_events as collector_fixtures

from yoke_core.domain import frontend_events_storage as storage

from yoke_contracts.timestamps import format_instant, parse_instant

from runtime.api.domain.test_sign_in_resolution import conn as actor_database
from yoke_core.domain.frontend_events_storage import (
    RATE_REQUESTS,
    admit_client,
    collector_identity,
)

conn = actor_database
client = collector_fixtures.client
database = collector_fixtures.database
event = collector_fixtures.event
headers = collector_fixtures.headers


def test_collector_signing_key_is_durable_and_publishable_key_is_not_secret(conn):
    org, public, secret = collector_identity(conn)
    assert len(secret) >= 32
    assert public != secret
    assert collector_identity(conn) == (org, public, secret)
    conn.rollback()
    assert collector_identity(conn) == (org, public, secret)


def test_rate_admission_is_shared_and_windows_expire(conn):
    org, _, _ = collector_identity(conn)
    for _ in range(RATE_REQUESTS):
        assert (
            admit_client(
                conn,
                org_id=org,
                client="transport-client",
                now=parse_instant("1970-01-01T00:02:00Z"),
            )
            == 0
        )
    assert (
        admit_client(
            conn,
            org_id=org,
            client="transport-client",
            now=parse_instant("1970-01-01T00:02:01Z"),
        )
        == 59
    )
    assert (
        admit_client(
            conn,
            org_id=org,
            client="another-client",
            now=parse_instant("1970-01-01T00:02:01Z"),
        )
        == 0
    )
    assert (
        admit_client(
            conn,
            org_id=org,
            client="transport-client",
            now=parse_instant("1970-01-01T00:03:00Z"),
        )
        == 0
    )


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_rate_window_start_is_native_and_retains_utc_epoch_alignment(conn, zone):
    conn.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    org, _, _ = collector_identity(conn)
    before = datetime(
        1969, 12, 31, 18, 29, 59, 123456, timezone(timedelta(hours=-5, minutes=-30))
    )
    for _ in range(RATE_REQUESTS):
        assert admit_client(conn, org_id=org, client="native-window", now=before) == 0
    assert admit_client(conn, org_id=org, client="native-window", now=before) == 1
    stored, kind = conn.execute(
        "SELECT window_start,pg_typeof(window_start)::text FROM frontend_event_rate_limits"
    ).fetchone()
    assert stored == parse_instant("1969-12-31T23:59:00Z")
    assert kind == "timestamp with time zone"
    assert (
        admit_client(
            conn,
            org_id=org,
            client="native-window",
            now=parse_instant("1970-01-01T00:00:00Z"),
        )
        == 0
    )


@pytest.mark.parametrize(
    "value",
    [
        "2026-10-08",
        "2026-10-08T00:00:00",
        "2026-10-08T00:00:00-00:00",
        "2026-10-08T00:00:00.1234567Z",
    ],
)
def test_collector_refuses_unqualified_or_excess_precision_instants(client, value):
    payload = {**event(), "event_time": value}
    response = client.post(
        "/api/events", json={"events": [payload]}, headers=headers(client)
    )
    assert response.status_code == 400
    assert response.json()["error"] == "envelope_invalid"


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
@pytest.mark.parametrize("micros", [0, 123456])
def test_collector_normalizes_client_and_receipt_instants(
    client, database, monkeypatch, zone, micros
):
    clock = datetime(1969, 12, 31, 23, 59, 59, micros, timezone.utc)
    receipt = clock + timedelta(seconds=3, microseconds=654321)
    monkeypatch.setattr(storage, "utc_now", lambda: receipt)
    offset = clock.astimezone(timezone(timedelta(hours=-5, minutes=-30)))
    payload = {**event(), "event_time": offset.isoformat(timespec="microseconds")}
    response = client.post(
        "/api/events", json={"events": [payload]}, headers=headers(client)
    )
    assert response.status_code == 200
    with database() as conn:
        conn.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
        instant, raw = conn.execute(
            "SELECT created_at,envelope FROM events WHERE event_id=%s",
            (payload["event_id"],),
        ).fetchone()
        assert instant == receipt
        assert instant.tzinfo is not None
        stored = json.loads(raw) if isinstance(raw, str) else raw
        assert stored["event_time"] == format_instant(clock)
        assert stored["received_at"] == format_instant(receipt)
        assert stored["client_time_offset_seconds"] == -4
