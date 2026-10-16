"""Current item and QA schema defaults and constraints."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _get_columns
from yoke_core.domain.workflow_registry import resolve_current_workflow_pin
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def _connect(db_path: str):
    """Backend-aware read connection to a :func:`init_test_db` database.

    Must be called inside the ``with init_test_db(...)`` block so the Postgres
    DSN repoint is still active.
    """
    return connect_test_db(db_path)


def _column_names(conn, table: str) -> list[str]:
    return _get_columns(conn, table)


def _issue_pin(conn) -> tuple[str, int]:
    return resolve_current_workflow_pin(conn, "issue")


class TestAddColumnMigrations:
    """ADD COLUMN migrations are idempotent and land on fresh DBs."""

    def test_source_column_defaults_to_no_recorded_source(self, tmp_path: Path) -> None:
        """A raw insert that names no source records none, never a literal actor id."""
        with init_test_db(tmp_path) as db_path:
            conn = _connect(db_path)
            workflow_id, workflow_version_id = _issue_pin(conn)
            conn.execute(
                "INSERT INTO items "
                "(id, project_id, project_sequence, title, workflow_id, "
                "workflow_version_id, status, priority, created_at, updated_at) "
                "VALUES (1, 1, 1, 'old', %s, %s, 'idea', 'medium', "
                "'2025-01-01', '2025-01-01')",
                (workflow_id, workflow_version_id),
            )
            conn.commit()
            row = conn.execute("SELECT source FROM items WHERE id=1").fetchone()
            assert row[0] == ""
            conn.close()

    def test_explicit_project_identity_is_preserved(self, tmp_path: Path) -> None:
        """Explicit project identity points to the seeded project."""
        with init_test_db(tmp_path) as db_path:
            conn = _connect(db_path)
            workflow_id, workflow_version_id = _issue_pin(conn)
            conn.execute(
                "INSERT INTO items "
                "(id, project_id, project_sequence, title, workflow_id, "
                "workflow_version_id, status, priority, created_at, updated_at) "
                "VALUES (1, 1, 1, 'test', %s, %s, 'idea', 'medium', "
                "'2025-01-01', '2025-01-01')",
                (workflow_id, workflow_version_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT i.project_id, i.project_sequence, p.slug "
                "FROM items i JOIN projects p ON p.id = i.project_id "
                "WHERE i.id=1"
            ).fetchone()
            assert row[0] == 1
            assert row[1] == 1
            assert row[2] == "yoke"
            conn.close()

    def test_structured_columns_present(self, tmp_path: Path) -> None:
        """structured columns exist after init."""
        with init_test_db(tmp_path) as db_path:
            conn = _connect(db_path)
            cols = _column_names(conn, "items")
            conn.close()
        for col in (
            "spec",
            "design_spec",
            "technical_plan",
            "worktree_plan",
            "shepherd_log",
            "shepherd_caveats",
            "test_results",
            "deploy_log",
        ):
            assert col in cols, f"Missing structured column: {col}"


class TestQaExecutionStatus:
    """Current QA execution status constraints and immutable verdict evidence."""


    def _seed_qa_row(
        self,
        conn,
        *,
        item_id: int,
        qa_kind: str,
        verdict: str | None,
        performed_by: str = "browser_substrate",
        qa_phase: str = "verification",
        success_policy: str = "",
    ) -> int:
        cur = conn.execute(
            "INSERT INTO qa_requirements (item_id, qa_kind, qa_phase, "
            "blocking_mode, requirement_source, success_policy, created_at) "
            "VALUES (%s, %s, %s, 'blocking', 'ac_derived', %s, %s) "
            "RETURNING id",
            (item_id, qa_kind, qa_phase, success_policy, "2026-01-01T00:00:00Z"),
        )
        req_id = cur.fetchone()[0]
        conn.execute(
            "INSERT INTO qa_runs (qa_requirement_id, performed_by, qa_kind, verdict, created_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (req_id, performed_by, qa_kind, verdict, "2026-01-01T00:00:00Z"),
        )
        return req_id

    def test_adds_column_on_init(self, tmp_path: Path) -> None:
        with init_test_db(tmp_path) as db_path:
            conn = _connect(db_path)
            cols = _column_names(conn, "qa_runs")
            conn.close()
        assert "execution_status" in cols


    def test_check_constraint_rejects_bogus_value(self, tmp_path: Path) -> None:
        with init_test_db(tmp_path) as db_path:
            conn = _connect(db_path)
            cur = conn.execute(
                "INSERT INTO qa_requirements (item_id, qa_kind, qa_phase, "
                "blocking_mode, requirement_source, created_at) "
                "VALUES (1, 'browser_smoke', 'verification', 'blocking', "
                "'ac_derived', '2026-01-01T00:00:00Z') "
                "RETURNING id"
            )
            req_id = cur.fetchone()[0]
            with pytest.raises(db_backend.integrity_error_types()):
                conn.execute(
                    "INSERT INTO qa_runs (qa_requirement_id, performed_by, qa_kind, execution_status, created_at) "
                    "VALUES (%s, 'browser_substrate', 'browser_smoke', 'bogus', '2026-01-01T00:00:00Z')",
                    (req_id,),
                )
            conn.close()


    def test_verdict_raw_result_immutable_after_verdict_set(
        self, tmp_path: Path
    ) -> None:
        with init_test_db(tmp_path) as db_path:
            conn = _connect(db_path)
            req_id = self._seed_qa_row(
                conn,
                item_id=11,
                qa_kind="ac_verification",
                verdict="pass",
                performed_by="agent",
            )
            run_id = conn.execute(
                "SELECT id FROM qa_runs WHERE qa_requirement_id = %s",
                (req_id,),
            ).fetchone()[0]
            conn.commit()

            with pytest.raises(db_backend.operational_error_types(conn)) as excinfo:
                conn.execute(
                    "UPDATE qa_runs SET raw_result = %s WHERE id = %s",
                    ("rewritten", run_id),
                )
            assert "immutable" in str(excinfo.value)
            conn.rollback()
            conn.close()
