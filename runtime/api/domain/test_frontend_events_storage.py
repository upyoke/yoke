"""Collector identity and rate admission survive process-local state loss."""

from datetime import datetime, timedelta, timezone

import pytest

from yoke_contracts.timestamps import parse_instant

from runtime.api.domain.test_sign_in_resolution import conn as actor_database
from yoke_core.domain.frontend_events_storage import (
    RATE_REQUESTS,
    admit_client,
    collector_identity,
)

conn = actor_database


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
