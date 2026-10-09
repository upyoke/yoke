"""Event fixture clocks and their real SQL writer preserve native precision."""

from datetime import datetime, timedelta
import sqlite3
import json

import pytest

from yoke_contracts.timestamps import format_instant, parse_instant

NOW = parse_instant("2060-10-08T00:00:00.123456Z")
OPAQUE = "2060-10-08T00:00:00+09:00 unchanged"
ENVELOPE = json.dumps({"context": {"clock_looking_value": OPAQUE}})


@pytest.mark.parametrize("zone", ["UTC", "America/Los_Angeles", "Asia/Kathmandu"])
def test_real_fixture_and_command_writers_keep_native_clocks(test_db, zone):
    from runtime.api import events_crud_full_test_helpers as full
    from runtime.api import events_crud_test_fixtures as basic

    test_db.execute("SELECT set_config('TimeZone', %s, true)", (zone,))
    row = full._insert_event_direct(
        test_db, event_id="fixture-clock", created_at=NOW, envelope=ENVELOPE
    )
    assert isinstance(row["created_at"], datetime) and row["created_at"] == NOW
    assert row["created_at"].microsecond == 123456 and row["envelope"] == ENVELOPE
    basic._insert_event(
        None, event_id="command-clock", created_at=NOW, envelope=ENVELOPE
    )
    row = test_db.execute(
        "SELECT created_at, envelope FROM events WHERE event_id='command-clock'"
    ).fetchone()
    assert (
        isinstance(row[0], datetime) and row[0] == NOW and row[0].microsecond == 123456
    )
    assert row[1] == ENVELOPE


def test_offset_clock_is_shared_native_and_does_not_truncate(monkeypatch):
    from runtime.api import events_crud_full_test_helpers as full
    from runtime.api import events_crud_test_fixtures as basic

    monkeypatch.setattr(basic, "utc_now", lambda: NOW)
    assert full._instant_offset_days is basic._instant_offset_days
    assert basic._instant_offset_days(-7) == NOW - timedelta(days=7)
    assert basic._instant_offset_days(1).microsecond == 123456
    assert isinstance(full._SEVEN_DAYS_AGO, datetime)
    assert isinstance(full._THIRTY_DAYS_AGO, datetime)
    monkeypatch.setattr(basic, "utc_now", lambda: datetime(2060, 10, 8))
    with pytest.raises(ValueError):
        basic._instant_offset_days(1)


@pytest.mark.parametrize(
    "invalid", ["", "2060-10-08", "2060-10-08T00:00:00", 0, datetime(2060, 10, 8)]
)
def test_event_writer_refuses_invalid_clock_before_lookup(monkeypatch, invalid):
    from yoke_core.domain import events_writes as writes

    monkeypatch.setattr(
        writes,
        "check_severity",
        lambda *args: pytest.fail("clock must refuse before reads"),
    )
    monkeypatch.setattr(
        writes,
        "connect",
        lambda *args: pytest.fail("clock must refuse before connection"),
    )
    with pytest.raises(ValueError):
        writes.cmd_insert(
            event_id=OPAQUE,
            source_type="system",
            session_id=OPAQUE,
            event_kind="system",
            event_type="test",
            event_name="TestEvent",
            created_at=invalid,
        )


def test_event_writer_refuses_naive_generated_clock_before_lookup(monkeypatch):
    from yoke_core.domain import events_writes as writes

    monkeypatch.setattr(writes, "utc_now", lambda: datetime(2060, 10, 8))
    monkeypatch.setattr(
        writes,
        "check_severity",
        lambda *args: pytest.fail("clock must refuse before reads"),
    )
    with pytest.raises(ValueError):
        writes.cmd_insert(
            event_id=OPAQUE,
            source_type="system",
            session_id=OPAQUE,
            event_kind="system",
            event_type="test",
            event_name="TestEvent",
        )


def test_severity_fixture_explicit_sqlite_boundary_is_canonical():
    from runtime.api import events_crud_full_test_helpers as full

    with sqlite3.connect(":memory:") as conn:
        conn.execute(
            "CREATE TABLE severity_config (event_name TEXT, source_type TEXT, min_severity TEXT, "
            "created_at TEXT, UNIQUE(event_name, source_type))"
        )
        full._setup_severity_config(conn)
        row = conn.execute("SELECT created_at FROM severity_config").fetchone()
        assert row[0] == format_instant(parse_instant("2026-01-01T00:00:00Z"))
