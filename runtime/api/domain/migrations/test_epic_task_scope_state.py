"""Rehearsal regressions for explicit generated-task scope migration."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog_inserts import insert_epic_task, insert_item
from yoke_core.domain.epic_task_scope import (
    TaskScopeIncomplete,
    finalize_generated_task_scopes,
)
from yoke_core.domain.migrations.epic_task_scope_state import apply, invariants


def test_empty_legacy_eight_task_plan_is_typed_without_inference(test_db):
    insert_item(test_db, id=1687, workflow_id="epic", status="planned")
    for task_num in range(1, 9):
        insert_epic_task(
            test_db,
            epic_id=1687,
            task_num=task_num,
            status="planned",
        )

    report = apply(test_db, tenant_id=4)
    invariants(test_db)

    assert report.deferred_tasks == tuple((1687, task) for task in range(1, 9))
    assert report.diagnostics[0] == (
        "tenant=4 item=YOK-1687 task=1 scope=legacy_deferred"
    )
    states = test_db.execute(
        "SELECT task_num, scope_state FROM epic_tasks "
        "WHERE epic_id=1687 ORDER BY task_num"
    ).fetchall()
    assert [(row["task_num"], row["scope_state"]) for row in states] == [
        (task, "legacy_deferred") for task in range(1, 9)
    ]
    with pytest.raises(TaskScopeIncomplete, match="deferred legacy scope"):
        finalize_generated_task_scopes(test_db, 1687)

    repeated = apply(test_db, tenant_id=4)
    assert repeated.path_tasks == ()
    assert repeated.deferred_tasks == ()


def test_terminal_historical_item_is_preserved_during_scope_repair(test_db):
    insert_item(test_db, id=407, workflow_id="epic", status="done")
    insert_epic_task(test_db, epic_id=407, task_num=1, status="done")

    report = apply(test_db, tenant_id=4)
    invariants(test_db)

    assert report.deferred_tasks == ((407, 1),)
    item = test_db.execute(
        "SELECT status FROM items WHERE id=407"
    ).fetchone()
    task = test_db.execute(
        "SELECT status, scope_state FROM epic_tasks "
        "WHERE epic_id=407 AND task_num=1"
    ).fetchone()
    assert item["status"] == "done"
    assert task["status"] == "done"
    assert task["scope_state"] == "legacy_deferred"
