"""Coverage for HC-session-pre-implementing-activity.

The detector flags any active work-claim whose item has been
pre-implementing for >30 minutes AND whose session emitted more than
10 ``HarnessToolCallCompleted`` events since claim acquisition. Lives
in its own file so the sibling :mod:`test_doctor_hc_session_cwd_binding`
stays under the authored-file cap.
"""

from __future__ import annotations

from typing import Any

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines import doctor_hc_session_cwd_binding as hc_module
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def _disposable_pg_db(ddl: str) -> Any:
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    if ddl:
        apply_fixture_ddl(conn, ddl)
    return pg_testdb.drop_database_on_close(conn, name)


def _make_pre_impl_conn() -> Any:
    """Schema that the stuck-pre-implementing detector reads
    (status + claimed_at + events)."""
    return _disposable_pg_db(
        """
        CREATE TABLE items (
            id INTEGER PRIMARY KEY, status TEXT, worktree TEXT,
            project_id INTEGER DEFAULT 1
        );
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY, session_id TEXT, target_kind TEXT,
            item_id INTEGER, epic_id INTEGER, task_num INTEGER,
            process_key TEXT, claimed_at TEXT, released_at TEXT
        );
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            session_id TEXT, event_name TEXT, created_at TEXT,
            envelope TEXT
        );
        """
    )


def _add_pre_impl_claim(
    conn, *, session_id, item_id, status, claimed_at,
):
    conn.execute(
        "INSERT INTO items (id, status, worktree, project_id) "
        "VALUES (%s, %s, %s, 1)",
        (item_id, status, f"YOK-{item_id}"),
    )
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, item_id, claimed_at) "
        "VALUES (%s, 'item', %s, %s)",
        (session_id, item_id, claimed_at),
    )
    conn.commit()


def _add_tool_calls(conn, *, session_id, count, base_time):
    for _ in range(count):
        conn.execute(
            "INSERT INTO events "
            "(session_id, event_name, created_at, envelope) "
            "VALUES (%s, 'HarnessToolCallCompleted', %s, '{}')",
            (session_id, base_time),
        )
    conn.commit()


class TestPreImplementingActivityHC:
    def test_stuck_pre_implementing_session_fails(self):
        conn = _make_pre_impl_conn()
        # Claim 60 minutes ago, status still refined-idea, many tool calls.
        old = "2026-05-17T15:00:00+00:00"
        _add_pre_impl_claim(
            conn, session_id="sess-stuck", item_id=9001,
            status="refined-idea", claimed_at=old,
        )
        _add_tool_calls(
            conn, session_id="sess-stuck", count=15, base_time=old,
        )
        rec = RecordCollector()

        hc_module.hc_session_pre_implementing_activity(
            conn, DoctorArgs(), rec,
        )

        assert rec.results[0].result == "FAIL"
        detail = rec.results[0].detail
        assert "sess-stuck" in detail
        assert "YOK-9001" in detail
        assert "refined-idea" in detail
        assert "tool_calls" in detail

    def test_implementing_status_not_flagged(self):
        conn = _make_pre_impl_conn()
        old = "2026-05-17T15:00:00+00:00"
        _add_pre_impl_claim(
            conn, session_id="sess-ok", item_id=9002,
            status="implementing", claimed_at=old,
        )
        _add_tool_calls(
            conn, session_id="sess-ok", count=99, base_time=old,
        )
        rec = RecordCollector()

        hc_module.hc_session_pre_implementing_activity(
            conn, DoctorArgs(), rec,
        )

        assert rec.results[0].result == "PASS"

    def test_recent_claim_under_threshold_not_flagged(self):
        conn = _make_pre_impl_conn()
        # Claim acquired moments in the future (effectively < 30 min ago).
        recent = "2099-01-01T00:00:00+00:00"
        _add_pre_impl_claim(
            conn, session_id="sess-fresh", item_id=9003,
            status="refined-idea", claimed_at=recent,
        )
        _add_tool_calls(
            conn, session_id="sess-fresh", count=50, base_time=recent,
        )
        rec = RecordCollector()

        hc_module.hc_session_pre_implementing_activity(
            conn, DoctorArgs(), rec,
        )

        assert rec.results[0].result == "PASS"

    def test_few_tool_calls_not_flagged(self):
        conn = _make_pre_impl_conn()
        old = "2026-05-17T15:00:00+00:00"
        _add_pre_impl_claim(
            conn, session_id="sess-quiet", item_id=9004,
            status="refined-idea", claimed_at=old,
        )
        _add_tool_calls(
            conn, session_id="sess-quiet", count=3, base_time=old,
        )
        rec = RecordCollector()

        hc_module.hc_session_pre_implementing_activity(
            conn, DoctorArgs(), rec,
        )

        assert rec.results[0].result == "PASS"

    def test_missing_items_table_passes(self):
        conn = _disposable_pg_db("")
        rec = RecordCollector()

        hc_module.hc_session_pre_implementing_activity(
            conn, DoctorArgs(), rec,
        )

        assert rec.results[0].result == "PASS"
        assert "missing" in rec.results[0].detail

    def test_missing_status_column_skips(self):
        # Minimal items schema without status: HC should skip gracefully.
        conn = _disposable_pg_db(
            """
            CREATE TABLE items (id INTEGER PRIMARY KEY, worktree TEXT);
            CREATE TABLE work_claims (
                id INTEGER PRIMARY KEY, session_id TEXT, item_id INTEGER,
                released_at TEXT
            );
            """
        )
        rec = RecordCollector()

        hc_module.hc_session_pre_implementing_activity(
            conn, DoctorArgs(), rec,
        )

        assert rec.results[0].result == "PASS"

    def test_released_claim_not_flagged(self):
        conn = _make_pre_impl_conn()
        old = "2026-05-17T15:00:00+00:00"
        _add_pre_impl_claim(
            conn, session_id="sess-done", item_id=9005,
            status="refined-idea", claimed_at=old,
        )
        conn.execute(
            "UPDATE work_claims SET released_at = %s WHERE session_id = %s",
            ("2026-05-17T15:30:00+00:00", "sess-done"),
        )
        _add_tool_calls(
            conn, session_id="sess-done", count=50, base_time=old,
        )
        conn.commit()
        rec = RecordCollector()

        hc_module.hc_session_pre_implementing_activity(
            conn, DoctorArgs(), rec,
        )

        assert rec.results[0].result == "PASS"
