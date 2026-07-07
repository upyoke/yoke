"""Tests for the governed migration harness — success/rollback/backup paths.

Companion file ``test_migration_harness_state.py`` covers helpers,
state-column write-through, and the CLI commands. Shared fixtures
(``tmp_db``, ``mock_backup``, ``mock_emit``) live in ``conftest.py``.

Verifies:
- Successful migration records audit trail
- Row-count mismatch triggers rollback
- Collateral damage (unaffected table change) triggers rollback
- Backup failure aborts before any DDL
"""

from __future__ import annotations

import json
import sqlite3
from unittest.mock import patch

import pytest

from yoke_core.domain.migration_harness import (
    AUDIT_TABLE,
    GovernedMigration,
    MigrationBackupError,
    MigrationVerificationError,
)


class TestGovernedMigrationSuccess:
    """Successful migration path."""

    def test_successful_migration_records_audit(self, tmp_db, mock_backup, mock_emit):
        """A migration that preserves row counts succeeds and records audit."""
        with GovernedMigration(
            name="test-add-column",
            tables=["items"],
            expected_deltas={"items": 0},
            description="Add a test column",
            db_path=tmp_db,
        ) as gm:
            gm.conn.execute("ALTER TABLE items ADD COLUMN test_col TEXT")
            gm.conn.commit()

        # Verify audit record
        conn = sqlite3.connect(tmp_db)
        row = conn.execute(
            f"SELECT migration_name, state, post_row_counts FROM {AUDIT_TABLE} "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "test-add-column"
        assert row[1] == "completed"
        post_counts = json.loads(row[2])
        assert post_counts["items"] == 10

    def test_expected_delta_honored(self, tmp_db, mock_backup, mock_emit):
        """Migration with expected row additions passes verification."""
        with GovernedMigration(
            name="test-insert",
            tables=["items"],
            expected_deltas={"items": 2},
            description="Add 2 items",
            db_path=tmp_db,
        ) as gm:
            gm.conn.execute(
                "INSERT INTO items (id, title, status, created_at, updated_at) "
                "VALUES (100, 'New 1', 'idea', '', '')"
            )
            gm.conn.execute(
                "INSERT INTO items (id, title, status, created_at, updated_at) "
                "VALUES (101, 'New 2', 'idea', '', '')"
            )
            gm.conn.commit()


class TestGovernedMigrationRollback:
    """Rollback scenarios."""

    def test_row_count_mismatch_triggers_rollback(self, tmp_db, mock_backup, mock_emit):
        """Deleting rows when delta=0 triggers rollback and restore."""
        with pytest.raises(MigrationVerificationError, match="expected 10 rows.*got 5"):
            with GovernedMigration(
                name="test-bad-delete",
                tables=["items"],
                expected_deltas={"items": 0},
                description="Should fail",
                db_path=tmp_db,
            ) as gm:
                gm.conn.execute("DELETE FROM items WHERE id > 5")
                gm.conn.commit()

        # Verify data was restored
        conn = sqlite3.connect(tmp_db)
        count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        conn.close()
        assert count == 10, f"Expected 10 rows restored, got {count}"

    def test_collateral_damage_triggers_rollback(self, tmp_db, mock_backup, mock_emit):
        """Changing an undeclared critical table triggers rollback."""
        with pytest.raises(MigrationVerificationError, match="COLLATERAL.*epic_tasks"):
            with GovernedMigration(
                name="test-collateral",
                tables=["items"],
                expected_deltas={"items": 0},
                description="Should fail on collateral",
                db_path=tmp_db,
            ) as gm:
                # Touch epic_tasks (not declared)
                gm.conn.execute("DELETE FROM epic_tasks WHERE task_num > 3")
                gm.conn.commit()

        # Verify both tables restored
        conn = sqlite3.connect(tmp_db)
        items_count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        tasks_count = conn.execute("SELECT COUNT(*) FROM epic_tasks").fetchone()[0]
        conn.close()
        assert items_count == 10
        assert tasks_count == 5

    def test_exception_during_migration_triggers_rollback(self, tmp_db, mock_backup, mock_emit):
        """An exception during the migration body triggers rollback."""
        with pytest.raises(RuntimeError, match="deliberate"):
            with GovernedMigration(
                name="test-exception",
                tables=["items"],
                expected_deltas={"items": 0},
                description="Should rollback on exception",
                db_path=tmp_db,
            ) as gm:
                gm.conn.execute("DELETE FROM items")
                gm.conn.commit()
                raise RuntimeError("deliberate failure")

        # Verify restored
        conn = sqlite3.connect(tmp_db)
        count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        conn.close()
        assert count == 10

    def test_audit_records_rollback(self, tmp_db, mock_backup, mock_emit):
        """Rolled-back migration records audit after restore.

        The backup is taken before the audit record is inserted, so
        restoring the backup removes the ``planned`` record. The
        rollback path re-opens the (restored) DB and inserts a fresh
        ``live_apply_failed`` audit record.
        """
        with pytest.raises(MigrationVerificationError):
            with GovernedMigration(
                name="test-audit-rollback",
                tables=["items"],
                expected_deltas={"items": 0},
                description="Should record rollback",
                db_path=tmp_db,
            ) as gm:
                gm.conn.execute("DELETE FROM items WHERE id > 5")
                gm.conn.commit()

        conn = sqlite3.connect(tmp_db)
        row = conn.execute(
            f"SELECT state, failure_reason FROM {AUDIT_TABLE} "
            "WHERE migration_name='test-audit-rollback'"
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "live_apply_failed"
        assert "expected 10 rows" in row[1]


class TestGovernedMigrationBackupFailure:
    """Backup failure prevents migration from starting."""

    def test_backup_failure_aborts(self, tmp_db, mock_emit):
        """If backup fails, no DDL runs."""
        with patch(
            "yoke_core.domain.migration_harness._run_backup",
            side_effect=MigrationBackupError("backup script missing"),
        ):
            with pytest.raises(MigrationBackupError, match="backup script missing"):
                with GovernedMigration(
                    name="test-no-backup",
                    tables=["items"],
                    expected_deltas={"items": 0},
                    db_path=tmp_db,
                ) as gm:
                    gm.conn.execute("DROP TABLE items")

        # Verify table still exists
        conn = sqlite3.connect(tmp_db)
        count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        conn.close()
        assert count == 10
