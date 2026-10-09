"""Native compact-sync flags and severity seed clocks at SQL ownership."""

from datetime import datetime, timedelta
import sqlite3

import pytest

from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain import backlog_github_compact_pending_flag as compact
from yoke_core.domain import db_helpers, events_schema
from runtime.api.fixtures.backlog_inserts import insert_item

MOMENT = parse_instant("2026-10-09T16:11:12.345678+05:45")
WIRE = "2026-10-09T10:26:12.345678Z"
ZONES = ["UTC", "America/New_York", "Asia/Kathmandu"]


@pytest.mark.parametrize("zone", ZONES)
def test_compact_flag_native_write_replaces_clock_then_clears_null(
    test_db, monkeypatch, zone
):
    insert_item(
        test_db, id=7, project_sequence=7, workflow_id="dash", status="implementing"
    )
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    monkeypatch.setattr(db_helpers, "utc_now", lambda: MOMENT)
    compact.record_sync_mode(test_db, 7, "compact")
    row = test_db.execute(
        "SELECT github_body_compact_pending FROM items WHERE id=7"
    ).fetchone()
    assert isinstance(row[0], datetime) and row[0] == MOMENT
    later = MOMENT + timedelta(microseconds=1)
    monkeypatch.setattr(db_helpers, "utc_now", lambda: later)
    compact.record_sync_mode(test_db, 7, "compact")
    assert (
        test_db.execute(
            "SELECT github_body_compact_pending FROM items WHERE id=7"
        ).fetchone()[0]
        == later
    )
    compact.record_sync_mode(test_db, 7, "full")
    assert (
        test_db.execute(
            "SELECT github_body_compact_pending FROM items WHERE id=7"
        ).fetchone()[0]
        is None
    )


def test_explicit_sqlite_compact_flag_formats_at_the_writer(monkeypatch):
    with sqlite3.connect(":memory:") as conn:
        conn.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, github_body_compact_pending TEXT)"
        )
        conn.execute("INSERT INTO items (id) VALUES (7)")
        monkeypatch.setattr(db_helpers, "utc_now", lambda: MOMENT)
        compact.record_sync_mode(conn, 7, "compact")
        assert (
            conn.execute("SELECT github_body_compact_pending FROM items").fetchone()[0]
            == WIRE
        )
        monkeypatch.setattr(db_helpers, "utc_now", lambda: MOMENT.replace(tzinfo=None))
        with pytest.raises(InvalidInstant):
            compact.record_sync_mode(conn, 7, "compact")
        assert (
            conn.execute("SELECT github_body_compact_pending FROM items").fetchone()[0]
            == WIRE
        )
        # Clearing does not need a clock and retains its nullable absence.
        compact.record_sync_mode(conn, 7, "full")
        assert (
            conn.execute("SELECT github_body_compact_pending FROM items").fetchone()[0]
            is None
        )


@pytest.mark.parametrize("zone", ZONES)
def test_severity_seed_preserves_native_microseconds_and_existing_seed(
    test_db, monkeypatch, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    events_schema.ensure_event_schema(test_db)
    test_db.execute(
        "DELETE FROM severity_config WHERE event_name='*' AND source_type='*'"
    )
    monkeypatch.setattr(events_schema, "utc_now", lambda: MOMENT)
    events_schema.ensure_event_schema(test_db)
    row = test_db.execute(
        "SELECT created_at FROM severity_config WHERE event_name='*' AND source_type='*'"
    ).fetchone()
    assert isinstance(row[0], datetime) and row[0] == MOMENT
    monkeypatch.setattr(
        events_schema, "utc_now", lambda: MOMENT + timedelta(microseconds=1)
    )
    events_schema.ensure_event_schema(test_db)
    assert (
        test_db.execute(
            "SELECT created_at FROM severity_config WHERE event_name='*' AND source_type='*'"
        ).fetchone()[0]
        == MOMENT
    )


def test_invalid_compact_clock_refuses_before_best_effort_savepoint(monkeypatch):
    monkeypatch.setattr(db_helpers, "utc_now", lambda: MOMENT.replace(tzinfo=None))
    with pytest.raises(InvalidInstant):
        compact.record_sync_mode(object(), 7, "compact")
