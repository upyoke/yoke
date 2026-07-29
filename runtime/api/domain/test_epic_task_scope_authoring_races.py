"""Repository-scope authoring races for generated tasks."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.backlog_inserts import insert_epic_task, insert_item
from yoke_core.domain import epic, epic_task_scope
from yoke_core.domain.epic_task_scope import TaskScopeIncomplete


def _author_scope(conn: Any, item_id: int, operation: str) -> None:
    if operation == "file_add":
        epic.file_add(conn, str(item_id), 1, "src/owned.py", "modify")
    else:
        epic_task_scope.set_no_files_scope(conn, item_id, 1)


def _race_scope_authors(
    *,
    connect: Callable[[], Any],
    item_id: int,
    first_operation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Exception]:
    first_locked = threading.Event()
    allow_first = threading.Event()
    second_attempted = threading.Event()
    second_finished = threading.Event()
    pause_guard = threading.Lock()
    pause_next = True
    outcomes: dict[str, Exception] = {}
    original_lock = epic_task_scope.lock_task_membership

    def pause_first_lock(conn: Any, locked_item_id: int) -> None:
        nonlocal pause_next
        original_lock(conn, locked_item_id)
        with pause_guard:
            should_pause = pause_next
            pause_next = False
        if should_pause:
            first_locked.set()
            assert allow_first.wait(timeout=5)

    monkeypatch.setattr(
        epic_task_scope,
        "lock_task_membership",
        pause_first_lock,
    )
    second_operation = "no_files" if first_operation == "file_add" else "file_add"

    def worker(operation: str, label: str) -> None:
        conn = connect()
        if label == "second":
            second_attempted.set()
        try:
            _author_scope(conn, item_id, operation)
        except Exception as exc:  # pragma: no cover - assertion reports value
            outcomes[f"{label}_error"] = exc
            conn.rollback()
        finally:
            if label == "second":
                second_finished.set()
            conn.close()

    first = threading.Thread(
        target=worker,
        args=(first_operation, "first"),
    )
    first.start()
    assert first_locked.wait(timeout=5)
    second = threading.Thread(
        target=worker,
        args=(second_operation, "second"),
    )
    second.start()
    assert second_attempted.wait(timeout=5)
    assert not second_finished.wait(timeout=0.2)
    allow_first.set()
    first.join(timeout=5)
    second.join(timeout=5)
    assert not first.is_alive()
    assert not second.is_alive()
    return outcomes


def _assert_outcome(
    outcomes: dict[str, Exception],
    first_operation: str,
) -> None:
    if first_operation == "file_add":
        assert set(outcomes) == {"second_error"}
        assert isinstance(outcomes["second_error"], TaskScopeIncomplete)
        assert "already has a file budget" in str(outcomes["second_error"])
    else:
        assert outcomes == {}


@pytest.mark.parametrize("first_operation", ["file_add", "no_files"])
def test_postgres_scope_authors_serialize_on_parent(
    test_db,
    monkeypatch,
    first_operation: str,
) -> None:
    item_id = 1821
    insert_item(test_db, id=item_id, workflow_id="epic", status="planned")
    insert_epic_task(
        test_db,
        epic_id=item_id,
        task_num=1,
        status="planned",
        scope_state="pending",
    )
    test_db.commit()
    database_name = test_db.info.dbname

    outcomes = _race_scope_authors(
        connect=lambda: pg_testdb.connect_test_database(database_name),
        item_id=item_id,
        first_operation=first_operation,
        monkeypatch=monkeypatch,
    )

    _assert_outcome(outcomes, first_operation)
    row = test_db.execute(
        "SELECT t.scope_state, COUNT(f.file_path) AS file_count "
        "FROM epic_tasks t LEFT JOIN epic_task_files f "
        "ON f.epic_id=t.epic_id AND f.task_num=t.task_num "
        "WHERE t.epic_id=%s AND t.task_num=1 "
        "GROUP BY t.scope_state",
        (item_id,),
    ).fetchone()
    assert (row["scope_state"], row["file_count"]) == ("paths", 1)


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
          scope_state TEXT NOT NULL DEFAULT 'pending',
          scope_finalized_at TEXT,
          UNIQUE(epic_id, task_num)
        );
        CREATE TABLE epic_task_files (
          id INTEGER PRIMARY KEY,
          epic_id INTEGER NOT NULL,
          task_num INTEGER NOT NULL,
          file_path TEXT NOT NULL,
          action TEXT,
          UNIQUE(epic_id, task_num, file_path)
        );
        INSERT INTO items (id, project_id) VALUES ({item_id}, 1);
        INSERT INTO epic_tasks (epic_id, task_num)
          VALUES ({item_id}, 1);
        """
    )
    conn.commit()
    conn.close()


@pytest.mark.parametrize("first_operation", ["file_add", "no_files"])
def test_sqlite_scope_authors_serialize_on_parent(
    tmp_path,
    monkeypatch,
    first_operation: str,
) -> None:
    item_id = 1822
    database_path = tmp_path / f"scope-{first_operation}.db"
    _create_sqlite_database(database_path, item_id)

    outcomes = _race_scope_authors(
        connect=lambda: sqlite3.connect(database_path, timeout=5),
        item_id=item_id,
        first_operation=first_operation,
        monkeypatch=monkeypatch,
    )

    _assert_outcome(outcomes, first_operation)
    conn = sqlite3.connect(database_path)
    row = conn.execute(
        "SELECT t.scope_state, COUNT(f.file_path) "
        "FROM epic_tasks t LEFT JOIN epic_task_files f "
        "ON f.epic_id=t.epic_id AND f.task_num=t.task_num "
        "WHERE t.epic_id=? AND t.task_num=1 "
        "GROUP BY t.scope_state",
        (item_id,),
    ).fetchone()
    conn.close()
    assert row == ("paths", 1)
