"""Unit tests for ``HC-event-outcome-enum-coverage``.

Each test isolates one HC branch against a disposable Postgres test
database seeded directly.
"""

from __future__ import annotations

from yoke_contracts.timestamps import parse_instant

from datetime import datetime, timedelta
from typing import List

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_project_checks import check_event_outcome_enum_coverage as mod
from yoke_project_checks.check_event_outcome_enum_coverage import (
    HC_ID,
    hc_event_outcome_enum_coverage,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_EVENTS_DDL = """
CREATE TABLE events (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    event_name TEXT NOT NULL,
    event_outcome TEXT,
    created_at TIMESTAMPTZ NOT NULL
);
"""


def _empty_conn():
    name = pg_testdb.create_test_database()
    return pg_testdb.drop_database_on_close(pg_testdb.connect_test_database(name), name)


@pytest.fixture
def db_conn():
    c = _empty_conn()
    apply_fixture_ddl(c, _EVENTS_DDL)
    yield c
    c.close()


def _seed_event(
    conn,
    *,
    event_id: str,
    event_name: str,
    event_outcome: str,
    created_at: datetime | str,
) -> None:
    conn.execute(
        "INSERT INTO events (event_id, event_name, event_outcome, "
        "created_at) VALUES (%s, %s, %s, %s)",
        (event_id, event_name, event_outcome, parse_instant(created_at)),
    )


def _outcomes(rec: RecordCollector) -> List[tuple[str, str, str]]:
    return [(r.check_id, r.result, r.detail) for r in rec.results]


def _args() -> DoctorArgs:
    return DoctorArgs()


class TestSkipWhenEventsTableMissing:
    def test_skips_on_minimal_fixture(self):
        conn = _empty_conn()
        try:
            rec = RecordCollector()
            hc_event_outcome_enum_coverage(conn, _args(), rec)
            assert _outcomes(rec) == [
                (f"HC-{HC_ID}", "SKIP", "events table not present on this DB"),
            ]
        finally:
            conn.close()


class TestLiveEventsScan:
    def test_fail_on_recent_non_enum_row(self, db_conn):
        _seed_event(
            db_conn,
            event_id="evt-1",
            event_name="HarnessToolCallDenied",
            event_outcome="ghost_outcome",
            created_at="2999-01-01T00:00:00Z",
        )
        rec = RecordCollector()
        hc_event_outcome_enum_coverage(db_conn, _args(), rec)
        assert rec.results[0].result == "FAIL"
        assert "ghost_outcome" in rec.results[0].detail

    def test_pass_when_only_enum_outcomes_present(self, db_conn):
        _seed_event(
            db_conn,
            event_id="evt-2",
            event_name="HarnessToolCallDenied",
            event_outcome="warn",
            created_at="2999-01-01T00:00:00Z",
        )
        _seed_event(
            db_conn,
            event_id="evt-3",
            event_name="HarnessToolCallDenied",
            event_outcome="suppression_attempted",
            created_at="2999-01-01T00:00:00Z",
        )
        rec = RecordCollector()
        hc_event_outcome_enum_coverage(db_conn, _args(), rec)
        assert rec.results[0].result == "PASS"

    def test_outside_three_day_window_ignored(self, db_conn):
        _seed_event(
            db_conn,
            event_id="evt-4",
            event_name="HarnessToolCallDenied",
            event_outcome="ghost_outcome",
            created_at="1999-01-01T00:00:00Z",
        )
        rec = RecordCollector()
        hc_event_outcome_enum_coverage(db_conn, _args(), rec)
        assert rec.results[0].result == "PASS"

    def test_other_event_class_outcomes_ignored(self, db_conn):
        _seed_event(
            db_conn,
            event_id="evt-5",
            event_name="PathClaimBashGuardDenied",
            event_outcome="blocked",
            created_at="2999-01-01T00:00:00Z",
        )
        rec = RecordCollector()
        hc_event_outcome_enum_coverage(db_conn, _args(), rec)
        assert rec.results[0].result == "PASS"


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_live_scan_cutoff_retains_microseconds_across_database_zones(
    db_conn, monkeypatch, zone
):
    now = parse_instant("2024-03-03T00:00:00.123456Z")
    cutoff = now - timedelta(days=3)
    monkeypatch.setattr(mod, "utc_now", lambda: now)
    db_conn.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    for name, delta in [("before", -1), ("equal", 0), ("after", 1)]:
        _seed_event(
            db_conn,
            event_id=name,
            event_name="HarnessToolCallDenied",
            event_outcome="ghost_outcome",
            created_at=cutoff + timedelta(microseconds=delta),
        )
    rows = mod._live_events_scan(db_conn)
    assert [tuple(row) for row in rows] == [("ghost_outcome", "after", 1)]
