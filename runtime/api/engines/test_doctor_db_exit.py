"""Tests for the Python doctor engine: exit-code behaviour.

Other doctor-db tests live in test_doctor_db.py, test_doctor_db_hcs_a.py,
and test_doctor_db_hcs_b.py.

Schema scaffolding shared via _doctor_db_test_helpers (private module).
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.engines.doctor import (
    DoctorArgs,
    _render_deferred_cleanup_addendum,
    run_checks,
)

from yoke_core.engines._doctor_db_test_helpers import apply_make_conn_schema
from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


class TestExitCode:
    def test_deferred_cleanup_addendum_honors_followup_order(self):
        name = pg_testdb.create_test_database()
        conn = pg_testdb.drop_database_on_close(
            pg_testdb.connect_test_database(name), name
        )
        conn.execute(
            "CREATE TABLE events ("
            "id INTEGER PRIMARY KEY, event_name TEXT, session_id TEXT, "
            "item_id TEXT, envelope TEXT, created_at TEXT)"
        )
        conn.execute(
            "INSERT INTO events "
            "(id, event_name, session_id, envelope, created_at) "
            "VALUES (1, 'HarnessSessionEnded', 'sess-a', '{}', 't1')"
        )
        conn.execute(
            "INSERT INTO events "
            "(id, event_name, session_id, item_id, envelope, created_at) "
            "VALUES (2, 'HarnessSessionEndDeferred', 'sess-a', '1643', "
            "'{\"defer_reason\":\"chain_pending\"}', 't2')"
        )
        conn.execute(
            "INSERT INTO events "
            "(id, event_name, session_id, item_id, envelope, created_at) "
            "VALUES (3, 'HarnessSessionEndDeferred', 'sess-b', '1644', "
            "'{\"defer_reason\":\"chain_pending\"}', 't3')"
        )
        conn.execute(
            "INSERT INTO events "
            "(id, event_name, session_id, envelope, created_at) "
            "VALUES (4, 'HarnessSessionEnded', 'sess-b', '{}', 't4')"
        )
        conn.commit()
        report = _render_deferred_cleanup_addendum(conn)
        conn.close()
        assert "sess-a" in report
        assert "chain_pending" in report
        assert "sess-b" not in report

    def test_exit_zero_all_pass(self, tmp_path):
        with init_test_db(tmp_path, apply_schema=apply_make_conn_schema) as db_path:
            conn = connect_test_db(db_path)
            conn.execute(
                "INSERT INTO items (id, title, type, status, priority) "
                "VALUES (1, 'OK', 'issue', 'idea', 'low')"
            )
            conn.commit()
            conn.close()

            args = DoctorArgs(db_path=db_path, only="status-consistency,backlog-hygiene")
            code = run_checks(args)
            assert code == 0

    def test_exit_one_on_fail(self, tmp_path):
        with init_test_db(tmp_path, apply_schema=apply_make_conn_schema) as db_path:
            conn = connect_test_db(db_path)
            conn.execute(
                "INSERT INTO items (id, title, type, status, priority) "
                "VALUES (10, 'E', 'epic', 'implementing', 'high')"
            )
            conn.commit()
            conn.close()

            args = DoctorArgs(db_path=db_path, only="status-consistency")
            code = run_checks(args)
            assert code == 1

    def test_file_output(self, tmp_path):
        report_path = str(tmp_path / "report.md")
        with init_test_db(tmp_path, apply_schema=apply_make_conn_schema) as db_path:
            conn = connect_test_db(db_path)
            conn.execute(
                "INSERT INTO items (id, title, type, status, priority) "
                "VALUES (1, 'OK', 'issue', 'idea', 'low')"
            )
            conn.commit()
            conn.close()

            args = DoctorArgs(db_path=db_path, file=report_path, only="status-consistency")
            run_checks(args)
        assert Path(report_path).exists()
        content = Path(report_path).read_text()
        assert "# Ouroboros Health Report" in content
