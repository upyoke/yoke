"""Shared fixtures for ``runtime/api/tests``.

Currently provides the migration-harness fixtures (``tmp_db``,
``mock_backup``, ``mock_emit``) used by both ``test_migration_harness.py``
and ``test_migration_harness_state.py``.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest

from yoke_core.domain.schema_init_apply import execute_schema_script


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temp DB with items, epic_tasks, events, and the
    final-shape migration_audit table seeded with data."""
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    execute_schema_script(conn, """
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'idea',
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE epic_tasks (
            id INTEGER PRIMARY KEY,
            epic_id INTEGER NOT NULL,
            task_num INTEGER NOT NULL,
            title TEXT,
            status TEXT DEFAULT 'planned',
            UNIQUE(epic_id, task_num)
        );
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            event_name TEXT,
            created_at TEXT DEFAULT ''
        );
        CREATE TABLE migration_audit (
            id INTEGER PRIMARY KEY,
            migration_name TEXT NOT NULL,
            description TEXT,
            tables_declared TEXT NOT NULL,
            expected_deltas TEXT NOT NULL,
            pre_row_counts TEXT NOT NULL,
            post_row_counts TEXT,
            pre_fk_violations INTEGER NOT NULL DEFAULT 0,
            post_fk_violations INTEGER,
            backup_path TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'planned'
                CHECK(state IN (
                    'planned','test_copy_created','test_applied',
                    'test_verified','rehearsed','backup_created',
                    'live_applied','live_verified','completed',
                    'test_copy_failed','test_apply_failed',
                    'test_verify_failed','backup_failed',
                    'live_apply_failed','live_verify_failed'
                )),
            failure_reason TEXT,
            exception_reason TEXT,
            source_fingerprint TEXT,
            rehearsed_at TEXT,
            lease_id INTEGER,
            test_copy_path TEXT,
            baseline_verify_result TEXT,
            author_verify_result TEXT,
            session_id TEXT,
            model_name TEXT,
            project_id INTEGER,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            duration_ms INTEGER
        );
    """)
    # Seed data
    for i in range(1, 11):
        conn.execute(
            "INSERT INTO items (id, title, status, created_at, updated_at) "
            "VALUES (?, ?, 'idea', '2026-01-01', '2026-01-01')",
            (i, f"Item {i}"),
        )
    for i in range(1, 6):
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title, status) "
            "VALUES (1, ?, ?, 'planned')",
            (i, f"Task {i}"),
        )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def mock_backup(tmp_path):
    """Mock _run_backup to create a real file copy instead of shelling out."""
    import shutil

    def _fake_backup(db_path, reason):
        backup_path = str(tmp_path / f"backup-{reason}.sqlite3")
        shutil.copy2(db_path, backup_path)
        return backup_path

    with patch("yoke_core.domain.migration_harness._run_backup", side_effect=_fake_backup):
        yield


@pytest.fixture
def mock_emit():
    """Mock _emit_event to avoid shelling out."""
    with patch("yoke_core.domain.migration_harness._emit_event"):
        yield
