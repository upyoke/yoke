"""Tests for the Python doctor engine: exit-code behaviour.

Other doctor-db tests live in test_doctor_db.py, test_doctor_db_hcs_a.py,
and test_doctor_db_hcs_b.py.

Schema scaffolding shared via _doctor_db_test_helpers (private module).
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.engines.doctor import (
    DoctorArgs,
    run_checks,
)

from yoke_core.engines._doctor_db_test_helpers import apply_make_conn_schema
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


class TestExitCode:
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
