"""Governed backfill tests for universal item worktree lane records."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from runtime.api.fixtures.backlog_inserts import (
    insert_epic_task,
    insert_item,
)
from yoke_core.domain.item_worktrees import list_item_worktrees
from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migrations.workflow_item_worktree_records import (
    apply,
    invariants,
)
from yoke_core.domain.workflow_behavior import (
    LANE_IMPLEMENTATION,
    LANE_INTEGRATION,
    LANE_WORKER,
)

_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name("workflow_item_worktree_records.migration.json")


def test_governed_manifest_is_valid_and_digest_bound():
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    source = payload["module_sources"]["workflow_item_worktree_records"]
    digest = hashlib.sha256((_ROOT / source["path"]).read_bytes()).hexdigest()
    assert digest == source["sha256"]


def test_backfill_preserves_legacy_rows_and_is_idempotent(test_db):
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
    first_count = int(
        test_db.execute("SELECT COUNT(*) FROM item_worktrees").fetchone()[0]
    )
    apply(test_db)
    invariants(test_db)

    assert first_count == int(
        test_db.execute("SELECT COUNT(*) FROM item_worktrees").fetchone()[0]
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
