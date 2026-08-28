"""Tests for HC-pretool-posttool-coverage."""

from __future__ import annotations

from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_project_checks import check_pretool_posttool_coverage as mod

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


_SESSIONS_DDL = """
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY,
    executor_surface TEXT
);
"""

_EVENTS_DDL = """
CREATE TABLE events (
    id SERIAL PRIMARY KEY,
    session_id TEXT,
    event_name TEXT,
    hook_event_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def _conn():
    name = pg_testdb.create_test_database()
    connection = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name,
    )
    apply_fixture_ddl(connection, _SESSIONS_DDL)
    apply_fixture_ddl(connection, _EVENTS_DDL)
    return connection


def test_coverage_inverts_respects_floor_and_ratio() -> None:
    assert mod.coverage_inverts(0, 29) is False
    assert mod.coverage_inverts(20, 30) is True
    assert mod.coverage_inverts(28, 30) is False
    assert mod.coverage_inverts(30, 30) is False


def test_missing_schema_skips_pass() -> None:
    name = pg_testdb.create_test_database()
    conn = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name,
    )
    rec = RecordCollector()
    mod.hc_pretool_posttool_coverage(conn, DoctorArgs(), rec)
    assert rec.results[0].result == "PASS"
    assert "skipping" in rec.results[0].detail
    conn.close()


def test_balanced_surface_passes() -> None:
    conn = _conn()
    conn.execute(
        "INSERT INTO harness_sessions (session_id, executor_surface) "
        "VALUES ('s1', 'claude-cli')"
    )
    for event_name, hook in (
        ("HarnessToolCallStarted", "PreToolUse"),
        ("HarnessToolCallCompleted", "PostToolUse"),
    ):
        conn.execute(
            "INSERT INTO events (session_id, event_name, hook_event_name) "
            "SELECT 's1', %s, %s FROM generate_series(1, 40)",
            (event_name, hook),
        )
    rec = RecordCollector()
    mod.hc_pretool_posttool_coverage(conn, DoctorArgs(), rec)
    assert rec.results[0].result == "PASS"
    conn.close()


def test_inverted_cursor_surface_fails() -> None:
    conn = _conn()
    conn.execute(
        "INSERT INTO harness_sessions (session_id, executor_surface) "
        "VALUES ('s1', 'cursor-cli')"
    )
    conn.execute(
        "INSERT INTO events (session_id, event_name, hook_event_name) "
        "SELECT 's1', 'HarnessToolCallStarted', 'PreToolUse' "
        "FROM generate_series(1, 20)"
    )
    conn.execute(
        "INSERT INTO events (session_id, event_name, hook_event_name) "
        "SELECT 's1', 'HarnessToolCallCompleted', 'PostToolUse' "
        "FROM generate_series(1, 40)"
    )
    rec = RecordCollector()
    mod.hc_pretool_posttool_coverage(conn, DoctorArgs(), rec)
    assert rec.results[0].result == "FAIL"
    assert "cursor-cli" in rec.results[0].detail
    conn.close()


def test_project_health_checks_registers_the_function() -> None:
    assert mod.PROJECT_HEALTH_CHECKS[0].fn is mod.hc_pretool_posttool_coverage
