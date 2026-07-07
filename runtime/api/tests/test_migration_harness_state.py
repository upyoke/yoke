"""State-column write-through, helper, and CLI tests for the migration harness.

Companion to ``test_migration_harness.py``. Verifies that the harness
writes only the ``state`` column on the canonical schema, the helper
functions used internally, and the ``cmd_audit_list`` / ``cmd_verify``
CLI fail-closed boundary.

Shared fixtures (``tmp_db``, ``mock_backup``, ``mock_emit``) live in
``conftest.py``.
"""

from __future__ import annotations

import sqlite3

import pytest

from yoke_core.domain.migration_harness import (
    AUDIT_TABLE,
    GovernedMigration,
    MigrationVerificationError,
    _count_all_tables,
    _fk_violation_count,
    cmd_audit_list,
    cmd_verify,
)
from yoke_core.domain.schema_common import _get_columns


def _init_full_schema_sqlite(db_path: str) -> None:
    """Build the legacy file-harness schema without touching backend env.

    The fixture ``SCHEMA_DDL`` is native Postgres text, so the SQLite
    validation file is initialized through canonical schema init instead —
    the same fully schema-inited shape a real install carries.
    """
    from yoke_core.domain.migration_audit_schema import (
        ensure_migration_audit_table,
    )
    from runtime.api.fixtures.schema_apply import apply_canonical_schema

    conn = sqlite3.connect(db_path)
    apply_canonical_schema(conn)
    ensure_migration_audit_table(conn)
    conn.close()


class TestHelpers:
    """Helper function tests."""

    def test_count_all_tables(self, tmp_db):
        conn = sqlite3.connect(tmp_db)
        counts = _count_all_tables(conn)
        conn.close()
        assert counts["items"] == 10
        assert counts["epic_tasks"] == 5
        assert counts["events"] == 0

    def test_fk_violation_count_clean(self, tmp_db):
        conn = sqlite3.connect(tmp_db)
        conn.execute("PRAGMA foreign_keys = ON")
        count = _fk_violation_count(conn)
        conn.close()
        assert count == 0


class TestGovernedMigrationStateWriteThrough:
    """``GovernedMigration`` writes only the ``state`` column. The test
    DB here is a fully schema-inited install so the harness exercises
    the same path it uses in production."""

    def test_state_column_written_on_success(self, mock_backup, mock_emit, tmp_path):
        db_path = str(tmp_path / "legacy-validation.sqlite3")
        _init_full_schema_sqlite(db_path)

        # Seed a single items row so the harness has something to see.
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority, flow, "
            "rework_count, frozen, created_at, updated_at, source, "
            "project_id, project_sequence) "
            "VALUES (1, 'test', 'issue', 'idea', 'medium', 'accelerated', 0, 0, "
            "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 'user', 1, 1)"
        )
        conn.commit()
        conn.close()

        with GovernedMigration(
            name="state-write-check",
            tables=["items"],
            expected_deltas={"items": 0},
            description="Verify state column is the sole status surface",
            db_path=db_path,
        ) as gm:
            gm.conn.execute("ALTER TABLE items ADD COLUMN state_check_tmp TEXT")
            gm.conn.commit()

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            f"SELECT state FROM {AUDIT_TABLE} "
            "WHERE migration_name = 'state-write-check'"
        ).fetchone()
        # Deliberate SQLite-file harness validation: this test builds an
        # explicit validation DB instead of the Yoke authority facade.
        columns = set(_get_columns(conn, AUDIT_TABLE))
        conn.close()
        assert "status" not in columns
        assert row is not None
        assert row[0] == "completed"

    def test_state_column_rollback_branch(self, mock_backup, mock_emit, tmp_path):
        db_path = str(tmp_path / "legacy-validation.sqlite3")
        _init_full_schema_sqlite(db_path)

        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority, flow, "
            "rework_count, frozen, created_at, updated_at, source, "
            "project_id, project_sequence) "
            "VALUES (1, 'test', 'issue', 'idea', 'medium', 'accelerated', 0, 0, "
            "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 'user', 1, 1)"
        )
        conn.commit()
        conn.close()

        with pytest.raises(MigrationVerificationError):
            with GovernedMigration(
                name="rollback-state-check",
                tables=["items"],
                expected_deltas={"items": 0},
                description="Trigger a verification failure",
                db_path=db_path,
            ) as gm:
                gm.conn.execute("DELETE FROM items WHERE id = 1")
                gm.conn.commit()

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            f"SELECT state FROM {AUDIT_TABLE} "
            "WHERE migration_name = 'rollback-state-check'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "live_apply_failed"


class TestCLI:
    """Retired path-based CLI command tests."""

    def test_audit_list_fails_closed(self, tmp_db, capsys):
        with pytest.raises(SystemExit) as exc:
            cmd_audit_list(tmp_db)
        captured = capsys.readouterr()
        assert exc.value.code == 1
        assert "retired" in captured.err
        assert "Postgres-native" in captured.err

    def test_verify_fails_closed(self, tmp_db, capsys):
        with pytest.raises(SystemExit) as exc:
            cmd_verify(tmp_db)
        captured = capsys.readouterr()
        assert exc.value.code == 1
        assert "retired" in captured.err
        assert "Postgres-native" in captured.err

    def test_governed_migration_requires_explicit_validation_db_path(self):
        with pytest.raises(ValueError, match="explicit legacy SQLite validation"):
            GovernedMigration(
                name="no-ambient-authority",
                tables=["items"],
                expected_deltas={"items": 0},
            )
