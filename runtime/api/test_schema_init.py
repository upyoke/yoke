"""Pytest coverage for ``yoke_core.domain.schema`` — fresh-DB init and
idempotency.

The init helpers route through :mod:`runtime.api.fixtures.file_test_db`, which
points each test at a disposable Postgres database. Schema introspection in the
helpers below goes through the backend-aware ``schema_common`` catalog helpers,
which resolve against ``information_schema`` on the Postgres authority.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import db_backend, schema
from yoke_core.domain.schema_common import (
    _column_is_not_null,
    _get_column_default,
    _get_columns,
    _get_columns_with_types,
    _get_indexes,
    _get_tables,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def _connect(db_path: str):
    """Backend-aware read connection to a :func:`init_test_db` database.

    Must be called inside the ``with init_test_db(...)`` block so the Postgres
    DSN repoint is still active.
    """
    return connect_test_db(db_path)


def _reinit(db_path: str) -> None:
    """Run ``schema.cmd_init`` a second time against the same test DB.

    Idempotency coverage re-applies the schema inside an active
    :func:`init_test_db` context. The context has already repointed
    ``YOKE_PG_DSN`` at the per-test database, so a bare ``cmd_init`` targets
    it.
    """
    schema.cmd_init()


def _table_names(conn) -> set[str]:
    return set(_get_tables(conn))


def _index_names(conn) -> set[str]:
    return set(_get_indexes(conn))


def _column_names(conn, table: str) -> list[str]:
    return _get_columns(conn, table)


class TestCmdInit:
    """cmd_init creates DB, tables, indexes, and ADD COLUMN migrations."""

    def test_creates_core_tables(self, tmp_path: Path) -> None:
        with init_test_db(tmp_path) as db_path:
            conn = _connect(db_path)
            tables = _table_names(conn)
            conn.close()

        expected_tables = {
            "items",
            "ouroboros_entries",
            "wrapup_reports",
            "release_entries",
            "epic_tasks",
            "epic_task_files",
            "epic_dispatch_chains",
            "epic_progress_notes",
            "qa_requirements",
            "qa_runs",
            "qa_artifacts",
            "merge_locks",
            "item_sections",
            "harness_sessions",
            "work_claims",
            "function_call_ledger",
            "path_claim_overrides",
        }
        assert expected_tables.issubset(tables), (
            f"Missing tables: {expected_tables - tables}"
        )

    def test_creates_indexes(self, tmp_path: Path) -> None:
        with init_test_db(tmp_path) as db_path:
            conn = _connect(db_path)
            indexes = _index_names(conn)
            conn.close()

        expected_indexes = {
            "idx_qa_requirements_item",
            "idx_qa_requirements_epic",
            "idx_qa_requirements_deployment",
            "idx_qa_runs_requirement",
            "idx_qa_artifacts_run",
            "idx_harness_sessions_lane",
            "idx_harness_sessions_heartbeat",
            "idx_work_claims_session",
            "idx_work_claims_session_released",
            "idx_work_claims_item",
            "idx_work_claims_heartbeat",
            "idx_function_call_ledger_created",
            "idx_path_claim_overrides_pair",
        }
        assert expected_indexes.issubset(indexes), (
            f"Missing indexes: {expected_indexes - indexes}"
        )

    def test_items_has_all_columns(self, tmp_path: Path) -> None:
        with init_test_db(tmp_path) as db_path:
            conn = _connect(db_path)
            cols = _column_names(conn, "items")
            conn.close()

        # Core + migration-added columns
        for col in (
            "id", "title", "type", "status", "priority", "source",
            "project_id", "project_sequence",
            "deployment_flow", "deploy_stage", "spec", "design_spec",
            "technical_plan", "worktree_plan", "shepherd_log", "shepherd_caveats",
            "test_results", "deploy_log",
            "spec_updated_at", "spec_updated_by",
        ):
            assert col in cols, f"items table missing column: {col}"
        # body and body_generated_at are retired
        for retired_col in ("body", "body_generated_at"):
            assert retired_col not in cols, f"items table still has retired column: {retired_col}"

    def test_items_has_db_mutation_profile_with_negative_default(self, tmp_path: Path) -> None:
        # Items.db_mutation_profile is a first-class structured field
        # with DB-level NOT NULL DEFAULT '{"state":"none"}'.
        with init_test_db(tmp_path) as db_path:
            conn = _connect(db_path)
            try:
                col_types = dict(_get_columns_with_types(conn, "items"))
                assert "db_mutation_profile" in col_types, (
                    "items table missing db_mutation_profile column"
                )
                default = _get_column_default(
                    conn, "items", "db_mutation_profile"
                )
                assert "TEXT" in col_types["db_mutation_profile"].upper()
                assert _column_is_not_null(
                    conn, "items", "db_mutation_profile"
                ), "db_mutation_profile must be NOT NULL"
                assert default is not None
                assert '"state"' in default
                assert '"none"' in default
            finally:
                conn.close()

    def test_items_has_db_compatibility_attestation_with_empty_default(
        self, tmp_path: Path,
    ) -> None:
        # Items.db_compatibility_attestation is a first-class peer
        # structured field with DB-level NOT NULL DEFAULT '{}'.
        with init_test_db(tmp_path) as db_path:
            conn = _connect(db_path)
            try:
                col_types = dict(_get_columns_with_types(conn, "items"))
                assert "db_compatibility_attestation" in col_types
                default = _get_column_default(
                    conn, "items", "db_compatibility_attestation"
                )
                assert "TEXT" in col_types["db_compatibility_attestation"].upper()
                assert _column_is_not_null(
                    conn, "items", "db_compatibility_attestation"
                )
                assert default is not None
                # Default is the empty JSON object literal.
                assert "{" in default and "}" in default
            finally:
                conn.close()

    def test_insert_into_items_yields_negative_default_profile(
        self, tmp_path: Path,
    ) -> None:
        # Every INSERT into items lands a row with a valid profile.
        # Direct-INSERT regression test — the DB-level default guarantees
        # that omitting the column still yields the negative default.
        with init_test_db(tmp_path) as db_path:
            conn = _connect(db_path)
            try:
                conn.execute(
                    "INSERT INTO items "
                    "(id, title, type, status, priority, project_id, "
                    "project_sequence, created_at, updated_at) "
                    "VALUES (777, 'item', 'issue', 'idea', 'medium', "
                    "1, 777, "
                    "'2026-04-23T00:00:00Z', '2026-04-23T00:00:00Z')"
                )
                conn.commit()
                row = conn.execute(
                    "SELECT db_mutation_profile, db_compatibility_attestation "
                    "FROM items WHERE id = 777"
                ).fetchone()
            finally:
                conn.close()
        assert row is not None
        assert row[0] == '{"state":"none"}'
        assert row[1] == "{}"

    def test_epic_tasks_has_migration_columns(self, tmp_path: Path) -> None:
        with init_test_db(tmp_path) as db_path:
            conn = _connect(db_path)
            cols = _column_names(conn, "epic_tasks")
            conn.close()

        for col in (
            "body", "github_issue", "branch", "worktree_path",
            "blocked_by", "max_attempts", "agent_id", "last_heartbeat",
            "last_activity_at",
        ):
            assert col in cols, f"epic_tasks missing column: {col}"

    def test_claim_chain_state_columns_present(self, tmp_path: Path) -> None:
        """claim-reason / release-intent / chain-state columns."""
        with init_test_db(tmp_path) as db_path:
            conn = _connect(db_path)
            claim_cols = _column_names(conn, "work_claims")
            session_cols = _column_names(conn, "harness_sessions")
            conn.close()

        for col in ("reason", "reason_intent", "release_reason_intent"):
            assert col in claim_cols, f"work_claims missing column: {col}"
        for col in ("last_chain_step", "last_checkpoint_at"):
            assert col in session_cols, f"harness_sessions missing column: {col}"

    def test_item_sections_has_source_column(self, tmp_path: Path) -> None:
        with init_test_db(tmp_path) as db_path:
            conn = _connect(db_path)
            cols = _column_names(conn, "item_sections")
            conn.close()
        assert "source" in cols

    def test_items_check_constraints_active(self, tmp_path: Path) -> None:
        """After init, invalid statuses are rejected by CHECK constraints."""
        with init_test_db(tmp_path) as db_path:
            conn = _connect(db_path)
            try:
                with pytest.raises(db_backend.integrity_error_types()):
                    conn.execute(
                        "INSERT INTO items (id, title, type, status, priority, created_at, updated_at) "
                        "VALUES (999, 'test', 'issue', 'BOGUS', 'medium', '2025-01-01', '2025-01-01')"
                    )
            finally:
                conn.close()

    def test_epic_tasks_check_constraints_active(self, tmp_path: Path) -> None:
        """After init, invalid epic_tasks statuses are rejected."""
        with init_test_db(tmp_path) as db_path:
            conn = _connect(db_path)
            try:
                with pytest.raises(db_backend.integrity_error_types()):
                    conn.execute(
                        "INSERT INTO epic_tasks (epic_id, task_num, title, status) "
                        "VALUES (1, 1, 'test', 'BOGUS')"
                    )
            finally:
                conn.close()

    def test_can_insert_valid_item(self, tmp_path: Path) -> None:
        """Smoke test: a valid item insert succeeds after init."""
        with init_test_db(tmp_path) as db_path:
            conn = _connect(db_path)
            conn.execute(
                "INSERT INTO items "
                "(id, title, type, status, priority, project_id, "
                "project_sequence, created_at, updated_at) "
                "VALUES (1, 'hello', 'issue', 'idea', 'medium', 1, 1, "
                "'2025-01-01', '2025-01-01')"
            )
            conn.commit()
            row = conn.execute("SELECT * FROM items WHERE id=1").fetchone()
            assert row is not None
            assert row["title"] == "hello"
            assert row["status"] == "idea"
            conn.close()


class TestInitIdempotent:
    """Calling cmd_init twice does not fail or lose data."""

    def test_double_init_no_error(self, tmp_path: Path) -> None:
        with init_test_db(tmp_path) as db_path:
            # First init ran at context entry; second call should succeed.
            _reinit(db_path)

    def test_double_init_preserves_data(self, tmp_path: Path) -> None:
        with init_test_db(tmp_path) as db_path:
            conn = _connect(db_path)
            conn.execute(
                "INSERT INTO items "
                "(id, title, type, status, priority, project_id, "
                "project_sequence, created_at, updated_at) "
                "VALUES (42, 'preserved', 'issue', 'idea', 'medium', 1, 42, "
                "'2025-01-01', '2025-01-01')"
            )
            conn.commit()
            conn.close()

            _reinit(db_path)

            conn = _connect(db_path)
            row = conn.execute("SELECT title FROM items WHERE id=42").fetchone()
            assert row is not None
            assert row[0] == "preserved"
            conn.close()

    def test_double_init_preserves_table_count(self, tmp_path: Path) -> None:
        with init_test_db(tmp_path) as db_path:
            conn = _connect(db_path)
            tables_first = _table_names(conn)
            conn.close()

            _reinit(db_path)

            conn = _connect(db_path)
            tables_second = _table_names(conn)
            conn.close()
            assert tables_first == tables_second
