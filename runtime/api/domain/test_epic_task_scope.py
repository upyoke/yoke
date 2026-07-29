"""Explicit generated-task scope finalization and runtime gates."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog_inserts import insert_epic_task, insert_item
from yoke_core.domain import epic
from yoke_core.domain.epic_dispatch import dispatch_chain_upsert
from yoke_core.domain.epic_task_scope import (
    TaskScopeIncomplete,
    finalize_generated_task_scopes,
    set_no_files_scope,
)
from yoke_core.domain.file_budget_required_gate import evaluate as budget_gate
from yoke_core.domain.update_status import update_task_status
from yoke_core.engines.doctor_hc_meta_epic_tasks import (
    hc_epic_task_scope_state,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def test_plan_finalization_is_atomic_when_one_task_scope_is_missing(test_db):
    insert_item(test_db, id=1700, workflow_id="epic", status="planned")
    insert_epic_task(test_db, epic_id=1700, task_num=1, status="planned")
    insert_epic_task(test_db, epic_id=1700, task_num=2, status="planned")
    epic.file_add(test_db, "1700", 1, "src/owned.py", "modify")

    with pytest.raises(TaskScopeIncomplete, match="task 2 has no explicit scope"):
        finalize_generated_task_scopes(test_db, 1700)

    rows = test_db.execute(
        "SELECT task_num, scope_state, scope_finalized_at FROM epic_tasks "
        "WHERE epic_id=1700 ORDER BY task_num"
    ).fetchall()
    assert [(row["scope_state"], row["scope_finalized_at"]) for row in rows] == [
        ("paths", None),
        ("pending", None),
    ]


def test_paths_and_explicit_no_files_finalize_and_pass_activation(test_db):
    insert_item(test_db, id=1701, workflow_id="epic", status="planned")
    insert_epic_task(test_db, epic_id=1701, task_num=1, status="planned")
    insert_epic_task(test_db, epic_id=1701, task_num=2, status="planned")
    epic.file_add(test_db, "1701", 1, "src/owned.py", "modify")
    set_no_files_scope(test_db, 1701, 2)

    finalize_generated_task_scopes(test_db, 1701)

    assert budget_gate(test_db, 1701)["verdict"] == "pass"
    states = test_db.execute(
        "SELECT task_num, scope_state, scope_finalized_at FROM epic_tasks "
        "WHERE epic_id=1701 ORDER BY task_num"
    ).fetchall()
    assert [row["scope_state"] for row in states] == ["paths", "no_files"]
    assert all(row["scope_finalized_at"] for row in states)


def test_health_check_reports_deferred_scope_on_active_item(test_db):
    insert_item(
        test_db,
        id=1702,
        workflow_id="epic",
        status="implementing",
    )
    insert_epic_task(
        test_db,
        epic_id=1702,
        task_num=1,
        status="implementing",
        scope_state="legacy_deferred",
        scope_finalized_at="2026-07-29T00:00:00Z",
    )
    rec = RecordCollector()

    hc_epic_task_scope_state(test_db, DoctorArgs(), rec)

    assert rec.results[0].check_id == "HC-epic-task-scope-state"
    assert rec.results[0].result == "WARN"
    assert "YOK-1702 task 1" in rec.results[0].detail


def test_task_activation_refuses_implicit_scope(test_db):
    insert_item(test_db, id=1703, workflow_id="epic", status="planned")
    insert_epic_task(test_db, epic_id=1703, task_num=1, status="planned")

    rc = update_task_status(
        test_db,
        "1703",
        "1",
        "implementing",
        no_rebuild=True,
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

    with pytest.raises(TaskScopeIncomplete, match="no explicit scope"):
        dispatch_chain_upsert(
            test_db,
            "1704",
            "codex/task",
            {"queue": ["001"]},
        )

    count = test_db.execute(
        "SELECT COUNT(*) AS count FROM epic_dispatch_chains "
        "WHERE epic_id=1704"
    ).fetchone()
    assert count["count"] == 0
