"""Tests for ``HC-event-severity-drift``."""

from __future__ import annotations

import uuid
from typing import Optional

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines.doctor_hc_event_severity_drift import (
    HC_ID,
    hc_event_severity_drift,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_DDL = """
CREATE TABLE events (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    severity TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE migration_audit (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    migration_name TEXT NOT NULL,
    state TEXT NOT NULL,
    completed_at TEXT
);
"""


def _make_conn(ddl: Optional[str] = _DDL):
    name = pg_testdb.create_test_database()
    c = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name
    )
    if ddl:
        apply_fixture_ddl(c, ddl)
    return c


@pytest.fixture
def conn():
    c = _make_conn()
    yield c
    c.close()


def _seed(
    conn,
    severity: str,
    *,
    created_at: str = "2026-05-19T18:30:00Z",
    event_id: Optional[str] = None,
) -> str:
    eid = event_id or str(uuid.uuid4())
    conn.execute(
        "INSERT INTO events (event_id, severity, created_at) VALUES (%s, %s, %s)",
        (eid, severity, created_at),
    )
    conn.commit()
    return eid


def _seed_audit(
    conn,
    migration_name: str,
    state: str,
    completed_at: Optional[str],
) -> None:
    conn.execute(
        "INSERT INTO migration_audit (migration_name, state, completed_at) "
        "VALUES (%s, %s, %s)",
        (migration_name, state, completed_at),
    )
    conn.commit()


def _run(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_event_severity_drift(conn, DoctorArgs(), rec)
    return rec


def test_pass_when_only_canonical_rows(conn) -> None:
    _seed(conn, "WARN")
    _seed(conn, "INFO")
    _seed(conn, "ERROR")

    rec = _run(conn)

    assert rec.results[-1].result == "PASS"
    assert rec.results[-1].check_id == f"HC-{HC_ID}"


def test_pass_when_events_table_absent() -> None:
    c = _make_conn("CREATE TABLE items (id INTEGER PRIMARY KEY)")

    rec = _run(c)
    c.close()

    assert rec.results[-1].result == "PASS"
    assert "events table absent" in rec.results[-1].detail


def test_fail_when_warning_residue_present_before_repair(conn) -> None:
    """AC-5: post-cutover residue makes the HC fail before repair."""
    _seed_audit(
        conn,
        "normalize-event-severity-casing",
        "completed",
        "2026-05-19T18:08:13Z",
    )
    _seed(
        conn,
        "WARNING",
        created_at="2026-05-19T18:30:00Z",
        event_id="evt-pre-repair",
    )

    rec = _run(conn)

    assert rec.results[-1].result == "FAIL"
    assert "WARNING=1" in rec.results[-1].detail
    assert "evt-pre-repair" in rec.results[-1].detail


def test_fail_reports_per_literal_counts_and_samples(conn) -> None:
    _seed(conn, "WARNING", event_id="a")
    _seed(conn, "WARNING", event_id="b")
    _seed(conn, "info", event_id="c")
    _seed(conn, "WARN", event_id="d")

    rec = _run(conn)

    detail = rec.results[-1].detail
    assert rec.results[-1].result == "FAIL"
    assert "WARNING=2" in detail
    assert "info=1" in detail
    assert "3 events row(s)" in detail


def test_fail_names_recent_severity_migration_when_present(conn) -> None:
    _seed_audit(
        conn,
        "normalize_warning_event_severity",
        "completed",
        "2026-05-20T17:40:00Z",
    )
    _seed(conn, "WARNING")

    rec = _run(conn)

    assert rec.results[-1].result == "FAIL"
    assert "normalize_warning_event_severity" in rec.results[-1].detail


def test_fail_omits_migration_clause_when_no_completed_audit(conn) -> None:
    _seed_audit(
        conn,
        "normalize_warning_event_severity",
        "live_apply_failed",
        None,
    )
    _seed(conn, "WARNING")

    rec = _run(conn)

    assert rec.results[-1].result == "FAIL"
    assert "Most recent severity-normalization migration" not in (
        rec.results[-1].detail
    )


def test_pass_after_repair_when_residue_cleared(conn) -> None:
    """AC-4: after residue repair, HC reports PASS."""
    _seed_audit(
        conn,
        "normalize_warning_event_severity",
        "completed",
        "2026-05-20T17:40:00Z",
    )
    # No 'WARNING' rows seeded — the migration cleared them.
    _seed(conn, "WARN")
    _seed(conn, "INFO")

    rec = _run(conn)

    assert rec.results[-1].result == "PASS"


def test_skip_when_events_read_raises(conn) -> None:
    conn.execute("DROP TABLE events")
    conn.execute(
        "CREATE TABLE events ("
        "  event_id TEXT PRIMARY KEY"
        ")"
    )  # severity column missing
    conn.commit()

    rec = _run(conn)

    assert rec.results[-1].result == "SKIP"
    assert "events read failed" in rec.results[-1].detail


def test_fail_omits_samples_when_sample_columns_are_absent() -> None:
    c = _make_conn("CREATE TABLE events (severity TEXT NOT NULL)")
    c.execute("INSERT INTO events (severity) VALUES ('WARNING')")
    c.commit()

    rec = _run(c)
    c.close()

    assert rec.results[-1].result == "FAIL"
    assert "WARNING=1" in rec.results[-1].detail
    assert "Sample rows:" not in rec.results[-1].detail
