from __future__ import annotations

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.domain.migration_apply import FAIL_LIVE_APPLY, STATE_COMPLETED
from yoke_core.engines.doctor import DoctorArgs, RecordCollector, hc_migration_audit


def _make_conn():
    name = pg_testdb.create_test_database()
    conn = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name
    )
    apply_fixture_ddl(
        conn,
        """
        CREATE TABLE items (id INTEGER PRIMARY KEY);
        CREATE TABLE epic_tasks (id INTEGER PRIMARY KEY);
        CREATE TABLE events (id INTEGER PRIMARY KEY);
        CREATE TABLE epic_progress_notes (id INTEGER PRIMARY KEY);
        CREATE TABLE qa_runs (id INTEGER PRIMARY KEY);
        CREATE TABLE migration_audit (
            id INTEGER PRIMARY KEY,
            migration_name TEXT NOT NULL,
            state TEXT NOT NULL,
            failure_reason TEXT,
            post_row_counts TEXT,
            started_at TEXT NOT NULL
        );
        """,
    )
    return conn


def _run(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_migration_audit(conn, DoctorArgs(project="yoke"), rec)
    return rec


def test_migration_audit_final_shape_failed_state_warns_without_status_column():
    conn = _make_conn()
    conn.execute(
        "INSERT INTO migration_audit "
        "(id, migration_name, state, failure_reason, started_at) "
        "VALUES (1, 'example', %s, 'live apply failed', "
        "'2026-04-24T00:00:00Z')",
        (FAIL_LIVE_APPLY,),
    )

    result = _run(conn).results[0]

    assert result.result == "WARN"
    assert FAIL_LIVE_APPLY in result.detail
    assert "live apply failed" in result.detail


def test_migration_audit_final_shape_completed_baseline_uses_state_column():
    conn = _make_conn()
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO items (id) VALUES (%s)",
            [(idx,) for idx in range(1, 21)],
        )
    conn.execute(
        "INSERT INTO migration_audit "
        "(id, migration_name, state, post_row_counts, started_at) "
        "VALUES (1, 'baseline', %s, '{\"items\": 20}', "
        "'2026-04-24T00:00:00Z')",
        (STATE_COMPLETED,),
    )

    result = _run(conn).results[0]

    assert result.result == "PASS"


def test_migration_audit_skips_failure_superseded_by_later_completed():
    """A failure row is silenced when a later row for the same
    ``migration_name`` reaches ``STATE_COMPLETED``. The DB keeps the
    failure row for audit history; the HC reports only un-superseded
    failures so that retry-then-success reads as PASS."""
    conn = _make_conn()
    conn.execute(
        "INSERT INTO migration_audit "
        "(id, migration_name, state, failure_reason, started_at) "
        "VALUES (1, 'retried_migration', %s, 'first attempt failed', "
        "'2026-05-10T00:00:00Z')",
        (FAIL_LIVE_APPLY,),
    )
    conn.execute(
        "INSERT INTO migration_audit "
        "(id, migration_name, state, started_at) "
        "VALUES (2, 'retried_migration', %s, '2026-05-11T00:00:00Z')",
        (STATE_COMPLETED,),
    )

    result = _run(conn).results[0]

    assert result.result == "PASS"


def test_migration_audit_keeps_failure_without_later_completed():
    """A failure with no later completed retry is still surfaced."""
    conn = _make_conn()
    conn.execute(
        "INSERT INTO migration_audit "
        "(id, migration_name, state, failure_reason, started_at) "
        "VALUES (1, 'unresolved_migration', %s, 'still broken', "
        "'2026-05-10T00:00:00Z')",
        (FAIL_LIVE_APPLY,),
    )

    result = _run(conn).results[0]

    assert result.result == "WARN"
    assert "unresolved_migration" in result.detail
