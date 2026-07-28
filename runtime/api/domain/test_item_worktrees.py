"""Universal item-worktree lane ownership and workflow-policy tests."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.item_worktrees import (
    list_item_worktrees,
    record_item_worktree,
    record_worker_item_worktree,
    release_item_worktrees,
    validate_item_worktree_roles,
)
from yoke_core.domain.workflow_behavior import (
    LANE_IMPLEMENTATION,
    LANE_INTEGRATION,
    LANE_WORKER,
)
from yoke_core.domain.workflow_item_binding_validation import (
    WorkflowItemBindingError,
)


def test_single_lane_record_refresh_and_release(test_db):
    insert_item(test_db, id=921, workflow_id="issue")
    first = record_item_worktree(
        test_db,
        item_id=921,
        branch="YOK-921",
        path="/tmp/yoke-921",
        lane_role=LANE_IMPLEMENTATION,
    )
    refreshed = record_item_worktree(
        test_db,
        item_id=921,
        branch="YOK-921",
        path="/tmp/yoke-921",
        lane_role=LANE_IMPLEMENTATION,
    )
    test_db.commit()

    assert refreshed["id"] == first["id"]
    assert "session_id" not in refreshed
    validate_item_worktree_roles(test_db, 921)
    assert release_item_worktrees(test_db, item_id=921) == 1
    assert list_item_worktrees(test_db, 921, active_only=True) == []


def test_workflow_policy_rejects_disallowed_lane_role(test_db):
    insert_item(test_db, id=922, workflow_id="issue")
    with pytest.raises(ValueError, match="does not allow"):
        record_item_worktree(
            test_db,
            item_id=922,
            branch="YOK-922-worker",
            path="/tmp/yoke-922-worker",
            lane_role=LANE_WORKER,
        )


def test_epic_worker_materializes_required_integration_lane(test_db):
    insert_item(test_db, id=923, workflow_id="epic")
    record_worker_item_worktree(
        test_db,
        item_id=923,
        branch="YOK-923-task-1",
        path="/tmp/yoke-923-task-1",
    )
    test_db.commit()

    rows = list_item_worktrees(test_db, 923, active_only=True)
    assert {row["lane_role"] for row in rows} == {
        LANE_WORKER,
        LANE_INTEGRATION,
    }
    validate_item_worktree_roles(test_db, 923)


def test_active_path_cannot_be_owned_by_two_items(test_db):
    insert_item(test_db, id=924, workflow_id="issue")
    insert_item(test_db, id=925, workflow_id="issue")
    record_item_worktree(
        test_db,
        item_id=924,
        branch="YOK-924",
        path="/tmp/shared-item-worktree",
        lane_role=LANE_IMPLEMENTATION,
    )
    with pytest.raises(ValueError, match="already owned"):
        record_item_worktree(
            test_db,
            item_id=925,
            branch="YOK-925",
            path="/tmp/shared-item-worktree",
            lane_role=LANE_IMPLEMENTATION,
        )


@pytest.mark.parametrize("status", ["done", "cancelled", "stopped"])
def test_terminal_item_cannot_recreate_active_lane(test_db, status):
    insert_item(
        test_db,
        id=926,
        workflow_id="issue",
        status=status,
    )

    with pytest.raises(WorkflowItemBindingError, match="is terminal"):
        record_item_worktree(
            test_db,
            item_id=926,
            branch=f"YOK-926-{status}",
            path=None,
            lane_role=LANE_IMPLEMENTATION,
        )
