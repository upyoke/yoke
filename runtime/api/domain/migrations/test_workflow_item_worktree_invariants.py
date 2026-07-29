"""Refusal and invariant tests for item-worktree migration records."""

from __future__ import annotations

import pytest

from runtime.api.domain.migrations.workflow_item_worktree_test_support import (
    add_legacy_epic_lane_columns,
)
from runtime.api.fixtures.backlog_inserts import insert_epic_task, insert_item
from yoke_core.domain.item_worktrees import list_item_worktrees
from yoke_core.domain.migrations import workflow_item_worktree_records as migration
from yoke_core.domain.migrations.workflow_item_worktree_records import (
    apply,
    invariants,
)


def test_conflicting_task_and_chain_paths_are_rejected_before_backfill(test_db):
    add_legacy_epic_lane_columns(test_db)
    insert_item(test_db, id=935, workflow_id="epic", status="implementing")
    insert_epic_task(
        test_db,
        epic_id=935,
        task_num=1,
        status="implementing",
        worktree="YOK-935-worker",
        branch="YOK-935-worker",
        worktree_path="/tmp/task-YOK-935-worker",
    )
    test_db.execute(
        "INSERT INTO epic_dispatch_chains "
        "(epic_id, worktree, worktree_path) VALUES (%s, %s, %s)",
        (935, "YOK-935-worker", "/tmp/chain-YOK-935-worker"),
    )
    test_db.commit()

    with pytest.raises(
        AssertionError,
        match=r"conflicting legacy worktree paths for item 935.*epic_tasks.*epic_dispatch_chains",
    ):
        apply(test_db)

    assert list_item_worktrees(test_db, 935) == []
    assert (
        test_db.execute(
            "SELECT item_worktree_id FROM epic_tasks WHERE epic_id=%s", (935,)
        ).fetchone()[0]
        is None
    )
    assert (
        test_db.execute(
            "SELECT item_worktree_id FROM epic_dispatch_chains WHERE epic_id=%s",
            (935,),
        ).fetchone()[0]
        is None
    )


def test_invariants_reject_worker_path_drift(test_db):
    add_legacy_epic_lane_columns(test_db)
    insert_item(test_db, id=936, workflow_id="epic")
    insert_epic_task(
        test_db,
        epic_id=936,
        task_num=1,
        worktree="YOK-936-worker",
        branch="YOK-936-worker",
        worktree_path="/tmp/YOK-936-worker",
    )
    test_db.execute(
        "INSERT INTO epic_dispatch_chains "
        "(epic_id, worktree, worktree_path) VALUES (%s, %s, %s)",
        (936, "YOK-936-worker", "/tmp/YOK-936-worker"),
    )
    test_db.commit()
    apply(test_db)

    lane_id = test_db.execute(
        "SELECT item_worktree_id FROM epic_tasks WHERE epic_id=%s", (936,)
    ).fetchone()[0]
    test_db.execute(
        "UPDATE item_worktrees SET path=%s WHERE id=%s",
        ("/tmp/drifted-YOK-936-worker", lane_id),
    )

    with pytest.raises(
        AssertionError,
        match=r"links to path '/tmp/drifted-YOK-936-worker'.*expected '/tmp/YOK-936-worker'",
    ):
        invariants(test_db)


def test_apply_rejects_legacy_source_row_count_change(test_db, monkeypatch):
    add_legacy_epic_lane_columns(test_db)
    insert_item(test_db, id=937, workflow_id="epic")
    insert_epic_task(
        test_db,
        epic_id=937,
        task_num=1,
        worktree="YOK-937-worker",
        branch="YOK-937-worker",
        worktree_path="/tmp/YOK-937-worker",
    )
    test_db.execute(
        "INSERT INTO epic_dispatch_chains "
        "(epic_id, worktree, worktree_path) VALUES (%s, %s, %s)",
        (937, "YOK-937-worker", "/tmp/YOK-937-worker"),
    )
    test_db.commit()
    original = migration._backfill_worker_lanes

    def destructive_backfill(conn, sources):
        original(conn, sources)
        conn.execute(
            "DELETE FROM epic_dispatch_chains WHERE epic_id=%s",
            (937,),
        )

    monkeypatch.setattr(
        migration,
        "_backfill_worker_lanes",
        destructive_backfill,
    )

    with pytest.raises(
        AssertionError,
        match=r"legacy worktree source row counts changed:.*epic_dispatch_chains.*1.*0",
    ):
        migration.apply(test_db)
