"""Governed contraction tests for superseded worktree source fields."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import insert_epic_task, insert_item
from yoke_core.domain.item_worktree_schema import (
    ensure_epic_item_worktree_references,
)
from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migration_source_digest import migration_source_digest
from yoke_core.domain.migrations.workflow_item_worktree_records import (
    apply as backfill_worktree_records,
)
from yoke_core.domain.migrations.workflow_item_worktree_source_fields_contract import (
    apply,
    invariants,
)
from yoke_core.domain.schema_common import _column_exists

_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name(
    "workflow_item_worktree_source_fields_contract.migration.json"
)
_RETIRED_COLUMNS = (
    ("item_worktrees", "session_id"),
    ("epic_tasks", "worktree"),
    ("epic_tasks", "branch"),
    ("epic_tasks", "worktree_path"),
    ("epic_dispatch_chains", "worktree"),
    ("epic_dispatch_chains", "worktree_path"),
)


def _restore_source_fields(conn) -> None:
    for table, column in _RETIRED_COLUMNS:
        if not _column_exists(conn, table, column):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
    conn.commit()


def _seed_legacy_worker_lane(conn, *, item_id: int) -> None:
    insert_item(conn, id=item_id, workflow_id="epic")
    insert_epic_task(
        conn,
        epic_id=item_id,
        task_num=1,
        status="done",
        worktree=f"YOK-{item_id}-worker",
        branch=f"YOK-{item_id}-worker",
        worktree_path=f"/tmp/YOK-{item_id}-worker",
    )
    conn.execute(
        "INSERT INTO epic_dispatch_chains "
        "(epic_id, worktree, worktree_path) VALUES (%s, %s, %s)",
        (
            item_id,
            f"YOK-{item_id}-worker",
            f"/tmp/YOK-{item_id}-worker",
        ),
    )
    conn.commit()


def test_governed_manifest_is_valid_and_digest_bound():
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    assert payload["profile"]["compatibility_class"] == "pre_merge_breaking"
    assert payload["profile"]["migration_strategy"] == "hard_cutover"
    source = payload["module_sources"]["workflow_item_worktree_source_fields_contract"]
    digest = migration_source_digest(_ROOT / source["path"])
    assert digest == source["sha256"]


def test_contract_preserves_rows_links_and_is_idempotent(test_db):
    _restore_source_fields(test_db)
    _seed_legacy_worker_lane(test_db, item_id=939)
    backfill_worktree_records(test_db)
    lane_id = int(
        test_db.execute(
            "SELECT item_worktree_id FROM epic_tasks WHERE epic_id=%s",
            (939,),
        ).fetchone()[0]
    )
    test_db.execute(
        "UPDATE item_worktrees SET session_id=%s WHERE id=%s",
        ("retired-session", lane_id),
    )
    test_db.commit()
    before = {
        table: int(test_db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in ("item_worktrees", "epic_tasks", "epic_dispatch_chains")
    }

    apply(test_db)
    invariants(test_db)

    assert all(
        not _column_exists(test_db, table, column) for table, column in _RETIRED_COLUMNS
    )
    assert before == {
        table: int(test_db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in before
    }
    assert (
        int(
            test_db.execute(
                "SELECT item_worktree_id FROM epic_tasks WHERE epic_id=%s",
                (939,),
            ).fetchone()[0]
        )
        == lane_id
    )
    assert (
        int(
            test_db.execute(
                "SELECT item_worktree_id FROM epic_dispatch_chains WHERE epic_id=%s",
                (939,),
            ).fetchone()[0]
        )
        == lane_id
    )

    apply(test_db)
    invariants(test_db)


def test_contract_refuses_unrepresented_usable_source(test_db):
    _restore_source_fields(test_db)
    _seed_legacy_worker_lane(test_db, item_id=940)
    ensure_epic_item_worktree_references(test_db)

    with pytest.raises(
        AssertionError,
        match=r"epic_tasks id=.*lacks an item worktree link",
    ):
        apply(test_db)

    assert all(
        _column_exists(test_db, table, column) for table, column in _RETIRED_COLUMNS
    )
