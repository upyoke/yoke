"""Governed backfill tests for universal item worktree lane records."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.domain.migrations.workflow_item_worktree_test_support import (
    add_legacy_epic_lane_columns,
)
from runtime.api.fixtures.backlog_inserts import (
    insert_epic_task,
    insert_item,
)
from yoke_core.domain.item_worktrees import (
    list_item_worktrees,
    record_item_worktree,
)
from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migration_source_digest import migration_source_digest
from yoke_core.domain.migrations.workflow_item_worktree_records import (
    apply,
    invariants,
)
from yoke_core.domain.workflow_behavior import (
    LANE_IMPLEMENTATION,
    LANE_INTEGRATION,
    LANE_WORKER,
)
from yoke_core.domain.workflow_item_binding_validation import (
    WorkflowItemBindingError,
)

_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name("workflow_item_worktree_records.migration.json")


def test_governed_manifest_is_valid_and_digest_bound():
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    assert payload["profile"]["compatibility_class"] == "pre_merge_safe"
    assert payload["profile"]["migration_strategy"] == "expand_contract"
    source = payload["module_sources"]["workflow_item_worktree_records"]
    digest = migration_source_digest(_ROOT / source["path"])
    assert digest == source["sha256"]


def test_backfill_preserves_legacy_rows_and_is_idempotent(test_db):
    add_legacy_epic_lane_columns(test_db)
    insert_item(
        test_db,
        id=931,
        workflow_id="issue",
        worktree="YOK-931",
    )
    insert_item(test_db, id=932, workflow_id="epic")
    insert_epic_task(
        test_db,
        epic_id=932,
        task_num=1,
        worktree="YOK-932-worker",
        branch="YOK-932-worker",
        worktree_path="/tmp/YOK-932-worker",
    )
    test_db.execute(
        "INSERT INTO epic_dispatch_chains "
        "(epic_id, worktree, worktree_path) VALUES (%s, %s, %s)",
        (932, "YOK-932-worker", "/tmp/YOK-932-worker"),
    )
    test_db.commit()
    before = {
        table: int(test_db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in ("items", "epic_tasks", "epic_dispatch_chains")
    }

    apply(test_db)
    invariants(test_db)
    first_lanes = [
        tuple(row)
        for row in test_db.execute(
            "SELECT id, item_id, branch, path, lane_role, state, "
            "created_at, updated_at, released_at "
            "FROM item_worktrees ORDER BY id"
        ).fetchall()
    ]
    first_links = {
        "task": test_db.execute(
            "SELECT item_worktree_id FROM epic_tasks WHERE epic_id=%s", (932,)
        ).fetchone()[0],
        "chain": test_db.execute(
            "SELECT item_worktree_id FROM epic_dispatch_chains WHERE epic_id=%s",
            (932,),
        ).fetchone()[0],
    }
    apply(test_db)
    invariants(test_db)

    assert first_lanes == [
        tuple(row)
        for row in test_db.execute(
            "SELECT id, item_id, branch, path, lane_role, state, "
            "created_at, updated_at, released_at "
            "FROM item_worktrees ORDER BY id"
        ).fetchall()
    ]
    assert first_links == {
        "task": test_db.execute(
            "SELECT item_worktree_id FROM epic_tasks WHERE epic_id=%s", (932,)
        ).fetchone()[0],
        "chain": test_db.execute(
            "SELECT item_worktree_id FROM epic_dispatch_chains WHERE epic_id=%s",
            (932,),
        ).fetchone()[0],
    }
    assert first_links["task"] == first_links["chain"]
    assert (
        test_db.execute(
            "SELECT path FROM item_worktrees WHERE id=%s",
            (first_links["task"],),
        ).fetchone()[0]
        == "/tmp/YOK-932-worker"
    )
    assert before == {
        table: int(test_db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in before
    }
    assert {
        row["lane_role"] for row in list_item_worktrees(test_db, 931, active_only=True)
    } == {LANE_IMPLEMENTATION}
    assert {
        row["lane_role"] for row in list_item_worktrees(test_db, 932, active_only=True)
    } == {LANE_WORKER, LANE_INTEGRATION}


def test_backfill_ignores_cross_workflow_epic_table_residue(test_db):
    add_legacy_epic_lane_columns(test_db)
    insert_item(
        test_db,
        id=933,
        workflow_id="issue",
        worktree="YOK-933",
    )
    insert_epic_task(
        test_db,
        epic_id=933,
        task_num=1,
        worktree="YOK-933-stale",
        branch="YOK-933-stale",
        worktree_path="/tmp/YOK-933-stale",
    )
    test_db.execute(
        "INSERT INTO epic_dispatch_chains "
        "(epic_id, worktree, worktree_path) VALUES (%s, %s, %s)",
        (933, "YOK-933-stale", "/tmp/YOK-933-stale"),
    )
    test_db.commit()

    apply(test_db)
    invariants(test_db)

    assert [
        (row["branch"], row["lane_role"])
        for row in list_item_worktrees(test_db, 933, active_only=True)
    ] == [("YOK-933", LANE_IMPLEMENTATION)]


def test_terminal_sources_are_released_and_absent_values_stay_unassigned(test_db):
    add_legacy_epic_lane_columns(test_db)
    insert_item(test_db, id=934, workflow_id="epic")
    insert_epic_task(
        test_db,
        epic_id=934,
        task_num=1,
        status="done",
        worktree=" NULL ",
        branch=" ",
        worktree_path=" /tmp/orphan ",
    )
    insert_epic_task(
        test_db,
        epic_id=934,
        task_num=2,
        status="done",
        worktree="YOK-934-worker",
        branch="YOK-934-worker",
    )
    test_db.execute(
        "INSERT INTO epic_dispatch_chains (epic_id, worktree) VALUES (%s, %s)",
        (934, "YOK-934-worker"),
    )
    test_db.commit()

    apply(test_db)
    rows = list_item_worktrees(test_db, 934)
    assert [(row["branch"], row["state"]) for row in rows] == [
        ("YOK-934-worker", "released"),
    ]
    task_rows = test_db.execute(
        "SELECT task_num, item_worktree_id FROM epic_tasks WHERE epic_id=%s ORDER BY task_num",
        (934,),
    ).fetchall()
    assert task_rows[0][1] is None
    assert task_rows[1][1] is not None
    chain_lane = test_db.execute(
        "SELECT item_worktree_id FROM epic_dispatch_chains WHERE epic_id=%s", (934,)
    ).fetchone()[0]
    assert chain_lane == task_rows[1][1]


def test_terminal_parent_dispatch_history_is_released_without_live_binding(
    test_db,
):
    add_legacy_epic_lane_columns(test_db)
    insert_item(test_db, id=939, workflow_id="epic", status="done")
    insert_epic_task(
        test_db,
        epic_id=939,
        task_num=1,
        status="done",
    )
    test_db.execute(
        "INSERT INTO epic_dispatch_chains "
        "(epic_id, worktree, worktree_path) VALUES (%s, %s, %s)",
        (939, "feature/terminal-history", "/tmp/terminal-history"),
    )
    test_db.commit()

    apply(test_db)
    invariants(test_db)

    lane = test_db.execute(
        "SELECT iw.branch, iw.path, iw.lane_role, iw.state "
        "FROM epic_dispatch_chains AS chain "
        "JOIN item_worktrees AS iw ON iw.id = chain.item_worktree_id "
        "WHERE chain.epic_id=%s",
        (939,),
    ).fetchone()
    assert tuple(lane) == (
        "feature/terminal-history",
        "/tmp/terminal-history",
        LANE_WORKER,
        "released",
    )

    with pytest.raises(
        WorkflowItemBindingError,
        match="item 939 is terminal at workflow stage 'done'",
    ):
        record_item_worktree(
            test_db,
            item_id=939,
            branch="feature/live-resource",
            path=None,
            lane_role=LANE_WORKER,
        )


def test_released_path_divergence_is_normalized_without_owning_path(test_db):
    add_legacy_epic_lane_columns(test_db)
    insert_item(test_db, id=938, workflow_id="epic")
    for task_num in (1, 2):
        insert_epic_task(
            test_db,
            epic_id=938,
            task_num=task_num,
            status="done",
            worktree="feature/settings-json-merge",
            branch="feature/settings-json-merge",
            worktree_path="/tmp/worktree-feature-settings-json-merge",
        )
    test_db.execute(
        "INSERT INTO epic_dispatch_chains "
        "(epic_id, worktree, worktree_path) VALUES (%s, %s, %s)",
        (
            938,
            "feature/settings-json-merge",
            "/tmp/yoke-worktrees-feature-settings-json-merge",
        ),
    )
    test_db.commit()

    apply(test_db)
    invariants(test_db)

    task_lanes = {
        int(row[0])
        for row in test_db.execute(
            "SELECT item_worktree_id FROM epic_tasks WHERE epic_id=%s",
            (938,),
        ).fetchall()
    }
    chain_lane = int(
        test_db.execute(
            "SELECT item_worktree_id FROM epic_dispatch_chains WHERE epic_id=%s",
            (938,),
        ).fetchone()[0]
    )
    assert task_lanes == {chain_lane}
    assert tuple(
        test_db.execute(
            "SELECT path, lane_role, state FROM item_worktrees WHERE id=%s",
            (chain_lane,),
        ).fetchone()
    ) == (None, LANE_WORKER, "released")

    test_db.execute(
        "UPDATE item_worktrees SET path=%s WHERE id=%s",
        ("/tmp/worktree-feature-settings-json-merge", chain_lane),
    )
    test_db.commit()
    apply(test_db)
    invariants(test_db)
    assert (
        test_db.execute(
            "SELECT path FROM item_worktrees WHERE id=%s",
            (chain_lane,),
        ).fetchone()[0]
        is None
    )
