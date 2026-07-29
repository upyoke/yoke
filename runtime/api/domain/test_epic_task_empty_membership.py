"""Durable finalization of an empty generated-task membership."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.epic_task_crud import task_upsert
from yoke_core.domain.epic_task_membership import (
    MEMBERSHIP_FINALIZED_COLUMN,
)
from yoke_core.domain.epic_task_scope import (
    TaskScopeIncomplete,
    finalize_generated_task_scopes,
    reopen_generated_task_scopes,
)


def _race_empty_finalization(
    *,
    connect: Callable[[], Any],
    item_id: int,
) -> dict[str, object]:
    membership_read = threading.Event()
    allow_finalize = threading.Event()
    insert_attempted = threading.Event()
    insert_finished = threading.Event()
    outcomes: dict[str, object] = {}

    def finalize_worker() -> None:
        conn = connect()
        try:
            finalize_generated_task_scopes(
                conn,
                item_id,
                after_membership_read=lambda: (
                    membership_read.set(),
                    allow_finalize.wait(timeout=5),
                ),
            )
        except Exception as exc:  # pragma: no cover - assertion reports value
            outcomes["finalize_error"] = exc
        finally:
            conn.close()

    def insert_worker() -> None:
        conn = connect()
        insert_attempted.set()
        try:
            task_upsert(conn, str(item_id), 1, "Concurrent task")
        except Exception as exc:  # pragma: no cover - assertion reports value
            outcomes["insert_error"] = exc
            conn.rollback()
        finally:
            insert_finished.set()
            conn.close()

    finalizer = threading.Thread(target=finalize_worker)
    finalizer.start()
    assert membership_read.wait(timeout=5)
    inserter = threading.Thread(target=insert_worker)
    inserter.start()
    assert insert_attempted.wait(timeout=5)
    assert not insert_finished.wait(timeout=0.2)
    allow_finalize.set()
    finalizer.join(timeout=5)
    inserter.join(timeout=5)
    assert not finalizer.is_alive()
    assert not inserter.is_alive()
    return outcomes


def _assert_finalized_empty_membership(conn: Any, item_id: int) -> None:
    marker = "%s" if not isinstance(conn, sqlite3.Connection) else "?"
    item = conn.execute(
        f"SELECT {MEMBERSHIP_FINALIZED_COLUMN} FROM items WHERE id={marker}",
        (item_id,),
    ).fetchone()
    value = item[MEMBERSHIP_FINALIZED_COLUMN] if hasattr(item, "keys") else item[0]
    assert value is not None
    task_count = conn.execute(
        f"SELECT COUNT(*) FROM epic_tasks WHERE epic_id={marker}",
        (item_id,),
    ).fetchone()
    assert task_count[0] == 0


def _assert_blocked_then_reopened(
    conn: Any,
    item_id: int,
    outcomes: dict[str, object],
) -> None:
    assert "finalize_error" not in outcomes
    assert isinstance(outcomes.get("insert_error"), TaskScopeIncomplete)
    assert "task membership is finalized" in str(outcomes["insert_error"])
    _assert_finalized_empty_membership(conn, item_id)
    assert reopen_generated_task_scopes(conn, item_id) == 1
    task_upsert(conn, str(item_id), 1, "Task after reopen")


def test_postgres_empty_membership_snapshot_blocks_concurrent_insert(
    test_db,
) -> None:
    item_id = 1823
    insert_item(test_db, id=item_id, workflow_id="epic", status="planned")
    test_db.commit()
    database_name = test_db.info.dbname

    outcomes = _race_empty_finalization(
        connect=lambda: pg_testdb.connect_test_database(database_name),
        item_id=item_id,
    )

    _assert_blocked_then_reopened(test_db, item_id, outcomes)


def _create_sqlite_database(database_path: Path, item_id: int) -> None:
    conn = sqlite3.connect(database_path)
    conn.executescript(
        f"""
        CREATE TABLE items (
          id INTEGER PRIMARY KEY,
          {MEMBERSHIP_FINALIZED_COLUMN} TEXT
        );
        CREATE TABLE epic_tasks (
          id INTEGER PRIMARY KEY,
          epic_id INTEGER NOT NULL,
          task_num INTEGER NOT NULL,
          title TEXT,
          item_worktree_id INTEGER,
          context_estimate TEXT,
          dependencies TEXT,
          status TEXT DEFAULT 'planning',
          body TEXT DEFAULT '',
          dispatch_attempts INTEGER DEFAULT 0,
          scope_state TEXT NOT NULL DEFAULT 'pending',
          scope_finalized_at TEXT,
          UNIQUE(epic_id, task_num)
        );
        CREATE TABLE epic_task_files (
          id INTEGER PRIMARY KEY,
          epic_id INTEGER NOT NULL,
          task_num INTEGER NOT NULL,
          file_path TEXT NOT NULL,
          action TEXT
        );
        INSERT INTO items (id) VALUES ({item_id});
        """
    )
    conn.commit()
    conn.close()


def test_sqlite_empty_membership_snapshot_blocks_concurrent_insert(
    tmp_path,
) -> None:
    item_id = 1824
    database_path = tmp_path / "empty-membership.db"
    _create_sqlite_database(database_path, item_id)

    outcomes = _race_empty_finalization(
        connect=lambda: sqlite3.connect(database_path, timeout=5),
        item_id=item_id,
    )

    conn = sqlite3.connect(database_path)
    _assert_blocked_then_reopened(conn, item_id, outcomes)
    conn.close()


def test_empty_membership_refuses_false_success_before_snapshot_migration(
    tmp_path,
) -> None:
    item_id = 1825
    database_path = tmp_path / "legacy-empty-membership.db"
    _create_sqlite_database(database_path, item_id)
    conn = sqlite3.connect(database_path)
    conn.execute(f"ALTER TABLE items DROP COLUMN {MEMBERSHIP_FINALIZED_COLUMN}")
    conn.commit()

    with pytest.raises(TaskScopeIncomplete, match="snapshot schema"):
        finalize_generated_task_scopes(conn, item_id)

    conn.close()
