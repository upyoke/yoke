"""Execution-authority regressions for legacy worker-lane migration."""

from __future__ import annotations

from runtime.api.domain.migrations.workflow_item_worktree_test_support import (
    add_legacy_epic_lane_columns,
)
from runtime.api.domain.path_claim_task_test_support import seed_session
from runtime.api.fixtures.backlog_inserts import insert_epic_task, insert_item
from yoke_core.domain.item_worktrees import list_item_worktrees
from yoke_core.domain.migrations.workflow_item_worktree_records import (
    apply,
    invariants,
)
from yoke_core.domain.workflow_behavior import LANE_INTEGRATION, LANE_WORKER


def test_pre_activation_sources_without_execution_authority_become_history(
    test_db,
) -> None:
    add_legacy_epic_lane_columns(test_db)
    insert_item(test_db, id=941, workflow_id="epic", status="planned")
    for task_num in range(1, 9):
        insert_epic_task(
            test_db,
            epic_id=941,
            task_num=task_num,
            status="planned",
            worktree="YOK-941",
        )

    insert_item(test_db, id=942, workflow_id="epic", status="plan-drafted")
    branches = (
        *(("YOK-942-foundation",) * 5),
        "YOK-942-cli",
        "YOK-942-hooks",
        "YOK-942-board-doctor",
        "YOK-942-foundation",
        "YOK-942-docs",
        "YOK-942-codex-role",
    )
    for task_num, branch in enumerate(branches, start=1):
        insert_epic_task(
            test_db,
            epic_id=942,
            task_num=task_num,
            status="plan-drafted",
            worktree=branch,
            branch=branch,
            worktree_path=f"/Users/operator/yoke/.worktrees/{branch}",
        )

    apply(test_db)
    invariants(test_db)
    apply(test_db)
    invariants(test_db)

    lanes_941 = list_item_worktrees(test_db, 941)
    assert [(lane["branch"], lane["path"], lane["state"]) for lane in lanes_941] == [
        ("YOK-941", None, "released"),
    ]
    lanes_942 = list_item_worktrees(test_db, 942)
    assert len(lanes_942) == 6
    assert {lane["state"] for lane in lanes_942} == {"released"}
    assert list_item_worktrees(test_db, 941, active_only=True) == []
    assert list_item_worktrees(test_db, 942, active_only=True) == []
    assert test_db.execute(
        "SELECT COUNT(*) FROM epic_tasks "
        "WHERE epic_id IN (%s, %s) AND item_worktree_id IS NOT NULL",
        (941, 942),
    ).fetchone()[0] == 19


def test_active_task_claim_keeps_pre_activation_worker_lane_active(test_db) -> None:
    add_legacy_epic_lane_columns(test_db)
    insert_item(test_db, id=943, workflow_id="epic", status="planned")
    insert_epic_task(
        test_db,
        epic_id=943,
        task_num=1,
        status="planned",
        worktree="YOK-943-worker",
        branch="YOK-943-worker",
        worktree_path="/tmp/YOK-943-worker",
    )
    seed_session(
        test_db,
        session_id="active-task-authority",
        item_id=943,
        task_num=1,
    )
    test_db.execute(
        "UPDATE work_claims SET released_at=%s "
        "WHERE target_kind='item' AND item_id=%s",
        ("2026-07-29T00:00:00Z", 943),
    )
    test_db.commit()

    apply(test_db)
    invariants(test_db)

    active = list_item_worktrees(test_db, 943, active_only=True)
    assert {lane["lane_role"] for lane in active} == {
        LANE_WORKER,
        LANE_INTEGRATION,
    }
    worker = next(lane for lane in active if lane["lane_role"] == LANE_WORKER)
    assert worker["path"] == "/tmp/YOK-943-worker"
