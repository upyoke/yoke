"""Pytest coverage for ADD COLUMN migrations and qa_runs status migration.

The init helpers route through the Postgres-only test-DB seam. Migration-replay
tests (drop column, re-init, verify backfill) run wholly inside one
``init_test_db`` context so every step targets the same per-test database.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import db_backend, schema
from yoke_core.domain.schema_common import _get_columns
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def _connect(db_path: str):
    """Backend-aware read connection to a :func:`init_test_db` database.

    Must be called inside the ``with init_test_db(...)`` block so the Postgres
    DSN repoint is still active.
    """
    return connect_test_db(db_path)


def _reinit(db_path: str) -> None:
    """Re-apply ``schema.cmd_init`` against the same test DB (migration replay).

    The active :func:`init_test_db` context has already repointed
    ``YOKE_PG_DSN``. ``db_path`` stays in the signature so call sites read
    like the older replay shape while authority comes from the DSN.
    """
    del db_path
    schema.cmd_init()


def _column_names(conn, table: str) -> list[str]:
    return _get_columns(conn, table)


class TestAddColumnMigrations:
    """ADD COLUMN migrations are idempotent and land on fresh DBs."""

    def test_source_column_actor_default(self, tmp_path: Path) -> None:
        """Items without an explicit source receive the canonical actor id."""
        with init_test_db(tmp_path) as db_path:
            conn = _connect(db_path)
            conn.execute(
                "INSERT INTO items "
                "(id, project_sequence, title, type, status, priority, created_at, updated_at) "
                "VALUES (1, 1, 'old', 'issue', 'idea', 'medium', '2025-01-01', '2025-01-01')"
            )
            conn.commit()
            row = conn.execute("SELECT source FROM items WHERE id=1").fetchone()
            assert row[0] == "2"
            conn.close()

    def test_project_identity_defaults_to_yoke(self, tmp_path: Path) -> None:
        """Project identity defaults to the seeded Yoke project id."""
        with init_test_db(tmp_path) as db_path:
            conn = _connect(db_path)
            conn.execute(
                "INSERT INTO items "
                "(id, project_sequence, title, type, status, priority, created_at, updated_at) "
                "VALUES (1, 1, 'test', 'issue', 'idea', 'medium', '2025-01-01', '2025-01-01')"
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
        for col in ("spec", "design_spec", "technical_plan", "worktree_plan",
                     "shepherd_log", "shepherd_caveats", "test_results",
                     "deploy_log"):
            assert col in cols, f"Missing structured column: {col}"

    def test_browser_qa_metadata_column_and_backfill(
        self, tmp_path: Path
    ) -> None:
        """browser_qa_metadata column exists and existing rows are backfilled
        with the canonical negative-default JSON.
        """
        from yoke_core.domain.browser_qa_metadata import NEGATIVE_DEFAULT_JSON

        with init_test_db(tmp_path) as db_path:
            # Simulate a pre-migration row: drop the column, insert, then rerun init
            conn = _connect(db_path)
            if "browser_qa_metadata" in _column_names(conn, "items"):
                conn.execute("ALTER TABLE items DROP COLUMN browser_qa_metadata")
                conn.commit()
            conn.execute(
                "INSERT INTO items (id, title, type, status, priority, "
                "created_at, updated_at, source, project_id, project_sequence) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (1, "t", "issue", "idea", "medium",
                 "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z",
                 "user", 1, 1),
            )
            conn.commit()
            conn.close()

            _reinit(db_path)

            conn = _connect(db_path)
            try:
                cols = _column_names(conn, "items")
                assert "browser_qa_metadata" in cols
                row = conn.execute(
                    "SELECT browser_qa_metadata FROM items WHERE id = 1"
                ).fetchone()
                assert row[0] == NEGATIVE_DEFAULT_JSON

                null_rows = conn.execute(
                    "SELECT COUNT(*) FROM items "
                    "WHERE browser_qa_metadata IS NULL "
                    "OR browser_qa_metadata = '' "
                    "OR browser_qa_metadata = 'null'"
                ).fetchone()[0]
                assert null_rows == 0
            finally:
                conn.close()


class TestQaExecutionStatusMigration:
    """ALTER TABLE adds execution_status and partitions existing browser rows."""

    def _drop_execution_status_column(self, db_path: str) -> None:
        """Simulate a pre-migration DB by dropping the column post-init.

        The caller's :func:`init_test_db` context has already applied the full
        schema; this just removes ``execution_status`` so the next
        :func:`_reinit` exercises the ALTER + partition backfill path.
        """
        conn = _connect(db_path)
        cols = _column_names(conn, "qa_runs")
        if "execution_status" in cols:
            conn.execute("ALTER TABLE qa_runs DROP COLUMN execution_status")
            conn.commit()
        conn.close()

    def _seed_qa_row(
        self,
        conn,
        *,
        item_id: int,
        qa_kind: str,
        verdict: str | None,
        executor_type: str = "browser_substrate",
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
            "INSERT INTO qa_runs (qa_requirement_id, executor_type, qa_kind, verdict, created_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (req_id, executor_type, qa_kind, verdict, "2026-01-01T00:00:00Z"),
        )
        return req_id

    def test_adds_column_on_init(self, tmp_path: Path) -> None:
        with init_test_db(tmp_path) as db_path:
            conn = _connect(db_path)
            cols = _column_names(conn, "qa_runs")
            conn.close()
        assert "execution_status" in cols

    def test_partitions_fail_rows_to_capture_failed(self, tmp_path: Path) -> None:
        with init_test_db(tmp_path) as db_path:
            self._drop_execution_status_column(db_path)
            conn = _connect(db_path)
            self._seed_qa_row(conn, item_id=1, qa_kind="browser_smoke", verdict="fail")
            conn.commit()
            conn.close()

            _reinit(db_path)

            conn = _connect(db_path)
            row = conn.execute(
                "SELECT execution_status, verdict FROM qa_runs"
            ).fetchone()
            conn.close()
        assert row["execution_status"] == "capture_failed"
        assert row["verdict"] == "fail"

    def test_preserves_pass_with_sibling_ac_evidence(self, tmp_path: Path) -> None:
        with init_test_db(tmp_path) as db_path:
            self._drop_execution_status_column(db_path)
            conn = _connect(db_path)
            self._seed_qa_row(conn, item_id=7, qa_kind="browser_smoke", verdict="pass")
            self._seed_qa_row(
                conn, item_id=7, qa_kind="ac_verification", verdict="pass",
                success_policy="visible change [requires_screenshot_evidence]",
            )
            conn.commit()
            conn.close()

            _reinit(db_path)

            conn = _connect(db_path)
            browser_row = conn.execute(
                "SELECT execution_status, verdict FROM qa_runs qr "
                "JOIN qa_requirements req ON req.id = qr.qa_requirement_id "
                "WHERE req.qa_kind = 'browser_smoke'"
            ).fetchone()
            conn.close()
        assert browser_row["execution_status"] == "captured"
        assert browser_row["verdict"] == "pass"

    def test_nulls_pass_without_inspection_evidence(self, tmp_path: Path) -> None:
        with init_test_db(tmp_path) as db_path:
            self._drop_execution_status_column(db_path)
            conn = _connect(db_path)
            self._seed_qa_row(conn, item_id=9, qa_kind="browser_smoke", verdict="pass")
            conn.commit()
            conn.close()

            _reinit(db_path)

            conn = _connect(db_path)
            row = conn.execute(
                "SELECT execution_status, verdict FROM qa_runs"
            ).fetchone()
            conn.close()
        assert row["execution_status"] == "captured"
        assert row["verdict"] is None

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
                    "INSERT INTO qa_runs (qa_requirement_id, executor_type, qa_kind, execution_status, created_at) "
                    "VALUES (%s, 'browser_substrate', 'browser_smoke', 'bogus', '2026-01-01T00:00:00Z')",
                    (req_id,),
                )
            conn.close()

    def test_migration_idempotent_on_second_init(self, tmp_path: Path) -> None:
        with init_test_db(tmp_path) as db_path:
            self._drop_execution_status_column(db_path)
            conn = _connect(db_path)
            self._seed_qa_row(conn, item_id=3, qa_kind="browser_smoke", verdict="pass")
            conn.commit()
            conn.close()

            _reinit(db_path)
            _reinit(db_path)  # Must not error or reset the column

            conn = _connect(db_path)
            cols = _column_names(conn, "qa_runs")
            row = conn.execute(
                "SELECT execution_status, verdict FROM qa_runs"
            ).fetchone()
            conn.close()
        assert "execution_status" in cols
        assert row["execution_status"] == "captured"
        assert row["verdict"] is None

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
                executor_type="agent",
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
