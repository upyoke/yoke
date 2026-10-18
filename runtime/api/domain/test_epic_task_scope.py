"""Generated-task Files Touched finalization and runtime gates."""

from __future__ import annotations

import sqlite3
import threading

import pytest
from runtime.api.fixtures.backlog_inserts import insert_epic_task, insert_item
from runtime.api.fixtures import pg_testdb
from runtime.api.task_files_touched_test_support import files_touched_body
from yoke_core.domain.epic_dispatch import dispatch_chain_upsert
from yoke_core.domain.epic_task_crud import task_upsert
from yoke_core.domain.epic_task_membership import membership_is_finalized
from yoke_core.domain.epic_task_scope import (
    TaskScopeIncomplete,
    finalize_generated_task_scopes,
    task_scope_issues,
)
from yoke_core.domain.file_budget_required_gate import evaluate as budget_gate
from yoke_core.domain.update_status import update_task_status
from yoke_core.engines.doctor_hc_meta_epic_tasks import (
    hc_epic_task_scope_state,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def test_plan_finalization_is_atomic_when_one_task_section_is_missing(test_db):
    insert_item(test_db, id=1700, workflow_id="epic", status="planned")
    insert_epic_task(
        test_db,
        epic_id=1700,
        task_num=1,
        status="planned",
        body=files_touched_body(["src/owned.py"]),
    )
    insert_epic_task(test_db, epic_id=1700, task_num=2, status="planned")

    with pytest.raises(
        TaskScopeIncomplete, match="task 2 has no ## Files Touched section"
    ) as refused:
        finalize_generated_task_scopes(test_db, 1700)

    assert "body-replace" in str(refused.value)
    assert not membership_is_finalized(test_db, 1700)


def test_paths_and_explicit_no_files_finalize_and_pass_activation(test_db):
    insert_item(test_db, id=1701, workflow_id="epic", status="planned")
    insert_epic_task(
        test_db,
        epic_id=1701,
        task_num=1,
        status="planned",
        body=files_touched_body(["src/owned.py"]),
    )
    insert_epic_task(
        test_db,
        epic_id=1701,
        task_num=2,
        status="planned",
        body=files_touched_body([]),
    )
    assert task_scope_issues(test_db, 1701) == [
        "YOK-1701 task membership is not finalized; recovery: "
        "`yoke workflow-item epic-task scope-finalize`"
    ]

    finalize_generated_task_scopes(test_db, 1701)

    assert budget_gate(test_db, 1701)["verdict"] == "pass"
    assert task_scope_issues(test_db, 1701) == []
    assert membership_is_finalized(test_db, 1701)


def test_section_naming_no_path_is_unparseable(test_db):
    insert_item(test_db, id=1702, workflow_id="epic", status="planned")
    insert_epic_task(
        test_db,
        epic_id=1702,
        task_num=1,
        status="planned",
        body="## Files Touched\n\n- the scheduler module\n",
    )

    issues = task_scope_issues(test_db, 1702)

    assert issues[0] == (
        "YOK-1702 task 1 has a ## Files Touched section that names no path "
        "and is not `None — no repository files`"
    )
    assert issues[1].startswith("recovery: write the task body's")


def test_health_check_reports_live_tasks_without_declared_files(test_db):
    insert_item(test_db, id=1705, workflow_id="epic", status="implementing")
    insert_epic_task(test_db, epic_id=1705, task_num=1, status="planned")
    insert_epic_task(
        test_db,
        epic_id=1705,
        task_num=2,
        status="planned",
        body="## Files Touched\n\nTBD\n",
    )
    insert_epic_task(
        test_db,
        epic_id=1705,
        task_num=3,
        status="planned",
        body=files_touched_body(["src/declared.py"]),
    )
    insert_item(test_db, id=1708, workflow_id="epic", status="planning")
    insert_epic_task(test_db, epic_id=1708, task_num=1, status="planned")
    rec = RecordCollector()

    hc_epic_task_scope_state(test_db, DoctorArgs(), rec)

    assert rec.results[0].check_id == "HC-epic-task-scope-state"
    assert rec.results[0].result == "WARN"
    detail = rec.results[0].detail
    assert "YOK-1705 task 1 has no ## Files Touched section" in detail
    assert "YOK-1705 task 2 has a ## Files Touched section" in detail
    assert "YOK-1705 task 3" not in detail
    assert "YOK-1708" not in detail
    assert "recovery:" in detail


def test_task_activation_refuses_implicit_scope(test_db):
    insert_item(test_db, id=1703, workflow_id="epic", status="planned")
    insert_epic_task(test_db, epic_id=1703, task_num=1, status="planned")

    rc = update_task_status(
        test_db,
        "1703",
        "1",
        "implementing",
        no_github=True,
    )

    assert rc == 1
    status = test_db.execute(
        "SELECT status FROM epic_tasks WHERE epic_id=1703 AND task_num=1"
    ).fetchone()
    assert status["status"] == "planned"


def test_dispatch_chain_refuses_implicit_scope(test_db):
    insert_item(test_db, id=1704, workflow_id="epic", status="planned")
    insert_epic_task(test_db, epic_id=1704, task_num=1, status="planned")

    with pytest.raises(TaskScopeIncomplete, match="no ## Files Touched section"):
        dispatch_chain_upsert(
            test_db,
            "1704",
            "codex/task",
            {"queue": ["001"]},
        )

    count = test_db.execute(
        "SELECT COUNT(*) AS count FROM epic_dispatch_chains WHERE epic_id=1704"
    ).fetchone()
    assert count["count"] == 0


def test_concurrent_task_insert_cannot_cross_plan_finalization(test_db):
    insert_item(test_db, id=1706, workflow_id="epic", status="planned")
    insert_epic_task(
        test_db,
        epic_id=1706,
        task_num=1,
        status="planned",
        body=files_touched_body([]),
    )
    membership_read = threading.Event()
    allow_finalize = threading.Event()
    insert_attempted = threading.Event()
    insert_finished = threading.Event()
    outcomes: dict[str, object] = {}
    database_name = test_db.info.dbname

    def pause_after_membership_read() -> None:
        membership_read.set()
        assert allow_finalize.wait(timeout=5)

    def finalize_worker() -> None:
        conn = pg_testdb.connect_test_database(database_name)
        try:
            finalize_generated_task_scopes(
                conn,
                1706,
                after_membership_read=pause_after_membership_read,
            )
        except Exception as exc:  # pragma: no cover - assertion reports value
            outcomes["finalize_error"] = exc
        finally:
            conn.close()

    def insert_worker() -> None:
        conn = pg_testdb.connect_test_database(database_name)
        insert_attempted.set()
        try:
            task_upsert(conn, "1706", 2, "Concurrent task")
        except Exception as exc:
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

    assert "finalize_error" not in outcomes
    assert isinstance(outcomes.get("insert_error"), TaskScopeIncomplete)
    assert "task membership is finalized" in str(outcomes["insert_error"])
    tasks = test_db.execute(
        "SELECT task_num FROM epic_tasks WHERE epic_id=1706 ORDER BY task_num"
    ).fetchall()
    assert len(tasks) == 1
    assert membership_is_finalized(test_db, 1706)


def test_sqlite_serializes_task_insert_against_finalization(tmp_path):
    database_path = tmp_path / "task-scope-race.db"
    setup = sqlite3.connect(database_path)
    setup.executescript(
        """
        CREATE TABLE items (
          id INTEGER PRIMARY KEY,
          generated_task_membership_finalized_at TEXT
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
          dispatch_attempts INTEGER DEFAULT 0,
          body TEXT,
          UNIQUE(epic_id, task_num)
        );
        INSERT INTO items (id) VALUES (1707);
        """
    )
    setup.execute(
        "INSERT INTO epic_tasks (epic_id, task_num, body) VALUES (1707, 1, ?)",
        (files_touched_body([]),),
    )
    setup.commit()
    setup.close()
    membership_read = threading.Event()
    allow_finalize = threading.Event()
    insert_attempted = threading.Event()
    outcomes: dict[str, object] = {}

    def finalize_worker() -> None:
        conn = sqlite3.connect(database_path, timeout=5)
        try:
            finalize_generated_task_scopes(
                conn,
                1707,
                after_membership_read=lambda: (
                    membership_read.set(),
                    allow_finalize.wait(timeout=5),
                ),
            )
        except Exception as exc:
            outcomes["finalize_error"] = exc
        finally:
            conn.close()

    def insert_worker() -> None:
        conn = sqlite3.connect(database_path, timeout=5)
        insert_attempted.set()
        try:
            task_upsert(conn, "1707", 2, "Concurrent task")
        except Exception as exc:
            outcomes["insert_error"] = exc
            conn.rollback()
        finally:
            conn.close()

    finalizer = threading.Thread(target=finalize_worker)
    finalizer.start()
    assert membership_read.wait(timeout=5)
    inserter = threading.Thread(target=insert_worker)
    inserter.start()
    assert insert_attempted.wait(timeout=5)
    allow_finalize.set()
    finalizer.join(timeout=5)
    inserter.join(timeout=5)

    assert "finalize_error" not in outcomes
    assert isinstance(outcomes.get("insert_error"), TaskScopeIncomplete)
    check = sqlite3.connect(database_path)
    rows = check.execute("SELECT task_num FROM epic_tasks ORDER BY task_num").fetchall()
    finalized = check.execute(
        "SELECT generated_task_membership_finalized_at FROM items WHERE id=1707"
    ).fetchone()
    check.close()
    assert len(rows) == 1
    assert finalized[0] is not None
