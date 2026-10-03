"""Primary lane selection agrees across deployment and branch readers."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.handlers.deployment_run_execution import _member_rows
from yoke_core.domain.item_worktree_resolution import primary_item_worktree_branch_sql
from yoke_core.domain.item_worktrees import (
    list_item_worktrees,
    primary_item_worktree,
    record_item_worktree,
    release_item_worktrees,
)


@pytest.fixture()
def lanes(test_db):
    item_id = 937
    insert_item(test_db, id=item_id, workflow_id="epic", status="implementing")
    rows = {}
    for role in ("worker", "implementation", "integration"):
        rows[role] = record_item_worktree(
            test_db,
            item_id=item_id,
            branch=f"topic/{role}",
            path=None,
            lane_role=role,
            validate_policy=False,
        )
    merged_head = "a" * 40
    test_db.execute(
        "UPDATE item_worktrees SET commit_sha=%s WHERE id=%s",
        (merged_head, rows["integration"]["id"]),
    )
    test_db.commit()
    return item_id, rows, merged_head


def test_primary_lane_prefers_newer_integration_and_preserves_inventory(test_db, lanes):
    item_id, rows, merged_head = lanes
    assert rows["worker"]["id"] < rows["integration"]["id"]
    primary = primary_item_worktree(test_db, item_id)
    assert primary["branch"] == rows["integration"]["branch"]
    assert primary["commit_sha"] == merged_head
    branch = test_db.execute(
        f"SELECT {primary_item_worktree_branch_sql('%s')}",
        (item_id,),
    ).fetchone()[0]
    assert branch == primary["branch"]
    assert list_item_worktrees(test_db, item_id, active_only=True)[0] == rows["worker"]


def test_primary_lane_filters_role_and_excludes_released_lanes(test_db, lanes):
    item_id, rows, _ = lanes
    assert primary_item_worktree(test_db, item_id, lane_role="worker") == rows["worker"]
    for role, next_role in (
        ("integration", "implementation"),
        ("implementation", "worker"),
    ):
        release_item_worktrees(test_db, item_id=item_id, branch=rows[role]["branch"])
        assert (
            primary_item_worktree(test_db, item_id)["branch"]
            == rows[next_role]["branch"]
        )
        assert primary_item_worktree(test_db, item_id, lane_role=role) is None
    release_item_worktrees(test_db, item_id=item_id)
    assert primary_item_worktree(test_db, item_id) is None


def test_deployment_member_reads_newer_merged_integration_lane(test_db, lanes):
    item_id, rows, _ = lanes
    run_id = "run-primary-lane-selection"
    test_db.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,status,created_at) "
        "VALUES (%s,1,'test-flow','created',%s)",
        (run_id, "2026-10-01T00:00:00Z"),
    )
    test_db.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at) VALUES (%s,%s,%s)",
        (run_id, item_id, "2026-10-01T00:00:00Z"),
    )
    test_db.commit()
    members = _member_rows(run_id)
    assert len(members) == 1
    assert members[0]["branch"] == rows["integration"]["branch"]
