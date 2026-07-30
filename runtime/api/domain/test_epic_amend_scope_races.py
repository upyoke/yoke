"""Membership amendment races against generated-task scope finalization."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.backlog_inserts import insert_epic_task, insert_item
from yoke_core.domain import epic_amend, epic_task_crud
from yoke_core.domain.epic_task_scope import finalize_generated_task_scopes


_EXPECTED_TASKS = {
    "add": [1, 2, 3],
    "split": [2, 3, 4],
    "remove": [2],
}


def _amend(conn: Any, item_id: int, operation: str) -> None:
    if operation == "add":
        epic_amend.task_add(conn, item_id, title="new")
    elif operation == "split":
        epic_amend.task_split(
            conn,
            item_id,
            1,
            [{"title": "child-a"}, {"title": "child-b"}],
        )
    else:
        epic_amend.task_remove(conn, item_id, 1)


def _race(
    *,
    connect: Callable[[], Any],
    item_id: int,
    operation: str,
) -> dict[str, object]:
    membership_read = threading.Event()
    allow_finalize = threading.Event()
    amend_attempted = threading.Event()
    amend_finished = threading.Event()
    outcomes: dict[str, object] = {}

    def pause_after_membership_read() -> None:
        membership_read.set()
        assert allow_finalize.wait(timeout=5)

    def finalize_worker() -> None:
        conn = connect()
        try:
            finalize_generated_task_scopes(
                conn,
                item_id,
                after_membership_read=pause_after_membership_read,
            )
        except Exception as exc:  # pragma: no cover - assertion reports value
            outcomes["finalize_error"] = exc
        finally:
            conn.close()

    def amend_worker() -> None:
        conn = connect()
        amend_attempted.set()
        try:
            _amend(conn, item_id, operation)
        except Exception as exc:  # pragma: no cover - assertion reports value
            outcomes["amend_error"] = exc
            conn.rollback()
        finally:
            amend_finished.set()
            conn.close()

    finalizer = threading.Thread(target=finalize_worker)
    finalizer.start()
    assert membership_read.wait(timeout=5)
    amendment = threading.Thread(target=amend_worker)
    amendment.start()
    assert amend_attempted.wait(timeout=5)
    assert not amend_finished.wait(timeout=0.2)
    allow_finalize.set()
    finalizer.join(timeout=5)
    amendment.join(timeout=5)
    assert not finalizer.is_alive()
    assert not amendment.is_alive()
    return outcomes


@pytest.mark.parametrize("operation", ["add", "split", "remove"])
def test_postgres_amendment_serializes_after_finalization(
    test_db,
    operation: str,
) -> None:
    item_id = 1720
    insert_item(test_db, id=item_id, workflow_id="epic", status="planned")
    for task_num in (1, 2):
        insert_epic_task(
            test_db,
            epic_id=item_id,
            task_num=task_num,
            status="planned",
            scope_state="no_files",
        )
    test_db.commit()
    database_name = test_db.info.dbname

    outcomes = _race(
        connect=lambda: pg_testdb.connect_test_database(database_name),
        item_id=item_id,
        operation=operation,
    )

    assert outcomes == {}
    rows = test_db.execute(
        "SELECT task_num, scope_finalized_at FROM epic_tasks "
        "WHERE epic_id=%s ORDER BY task_num",
        (item_id,),
    ).fetchall()
    assert [row["task_num"] for row in rows] == _EXPECTED_TASKS[operation]
    assert all(row["scope_finalized_at"] is None for row in rows)


def _create_sqlite_database(database_path: Path, item_id: int) -> None:
    conn = sqlite3.connect(database_path)
    conn.executescript(
        f"""
        CREATE TABLE items (
          id INTEGER PRIMARY KEY,
          project_id INTEGER
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
        INSERT INTO items (id, project_id) VALUES ({item_id}, 1);
        INSERT INTO epic_tasks
          (epic_id, task_num, title, scope_state)
          VALUES
          ({item_id}, 1, 'first', 'no_files'),
          ({item_id}, 2, 'second', 'no_files');
        """
    )
    conn.commit()
    conn.close()


@pytest.mark.parametrize("operation", ["add", "split", "remove"])
def test_sqlite_amendment_serializes_after_finalization(
    tmp_path,
    monkeypatch,
    operation: str,
) -> None:
    item_id = 1721
    database_path = tmp_path / f"scope-{operation}.db"
    _create_sqlite_database(database_path, item_id)
    monkeypatch.setattr(
        epic_task_crud,
        "touch_item_activity",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        epic_task_crud,
        "touch_epic_task_activity",
        lambda *args, **kwargs: None,
    )

    outcomes = _race(
        connect=lambda: sqlite3.connect(database_path, timeout=5),
        item_id=item_id,
        operation=operation,
    )

    assert outcomes == {}
    conn = sqlite3.connect(database_path)
    rows = conn.execute(
        "SELECT task_num, scope_finalized_at FROM epic_tasks "
        "ORDER BY task_num"
    ).fetchall()
    conn.close()
    assert [row[0] for row in rows] == _EXPECTED_TASKS[operation]
    assert all(row[1] is None for row in rows)
