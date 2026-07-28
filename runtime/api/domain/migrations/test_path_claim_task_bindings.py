"""Governed migration coverage for path-claim task bindings."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.domain.path_claim_task_test_support import (
    seed_epic,
    seed_item_claim,
    seed_target,
    seed_worker_task,
)
from runtime.api.domain.migrations import (
    path_claim_task_bindings as source_wrapper,
)
from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migration_source_digest import migration_source_digest
from yoke_core.domain.migrations.path_claim_task_bindings import (
    MIGRATION_NAME,
    UnsafeTaskBindingBackfill,
    apply,
    invariants,
)
from yoke_core.domain.schema_common import _table_exists


_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name("path_claim_task_bindings.migration.json")


def test_governed_manifest_is_valid_and_digest_bound() -> None:
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    source = payload["module_sources"][MIGRATION_NAME]
    assert migration_source_digest(_ROOT / source["path"]) == source["sha256"]


def test_source_checkout_wrapper_exposes_packaged_migration() -> None:
    assert source_wrapper.MIGRATION_NAME == MIGRATION_NAME
    assert source_wrapper.apply is apply
    assert source_wrapper.invariants is invariants


def test_apply_creates_additive_shape_and_repeat_apply_is_stable(test_db) -> None:
    test_db.execute("DROP TABLE IF EXISTS path_claim_task_bindings")
    assert not _table_exists(test_db, "path_claim_task_bindings")

    apply(test_db)
    invariants(test_db)
    apply(test_db)
    invariants(test_db)
    assert (
        test_db.execute("SELECT COUNT(*) FROM path_claim_task_bindings").fetchone()[0]
        == 0
    )


def test_apply_requires_worktree_record_contract_first(
    test_db,
    monkeypatch,
) -> None:
    from yoke_core.domain.migrations import path_claim_task_bindings as migration

    seed_epic(test_db, item_id=21301)
    real_column_exists = migration._column_exists

    def _without_task_lane(conn, table, column):
        if table == "epic_tasks" and column == "item_worktree_id":
            return False
        return real_column_exists(conn, table, column)

    monkeypatch.setattr(migration, "_column_exists", _without_task_lane)

    with pytest.raises(
        UnsafeTaskBindingBackfill,
        match="workflow_item_worktree_records must apply before",
    ):
        apply(test_db)


def test_apply_refuses_two_legacy_epics_with_nineteen_empty_task_budgets(
    test_db,
    tmp_path,
) -> None:
    task_num = 0
    for item_id, task_count in ((21302, 10), (21303, 9)):
        seed_epic(test_db, item_id=item_id)
        for local_num in range(1, task_count + 1):
            task_num += 1
            seed_worker_task(
                test_db,
                item_id=item_id,
                task_num=local_num,
                lane_path=tmp_path / f"worker-{task_num}",
            )
    test_db.execute("DROP TABLE path_claim_task_bindings")
    test_db.commit()

    with pytest.raises(
        UnsafeTaskBindingBackfill,
        match="epic_task_files budgets are empty",
    ):
        apply(test_db)

    assert not _table_exists(test_db, "path_claim_task_bindings")


def test_apply_backfills_only_persisted_budget_matches_and_repeats(
    test_db,
    tmp_path,
) -> None:
    item_id = seed_epic(test_db, item_id=21304)
    seed_worker_task(
        test_db,
        item_id=item_id,
        task_num=1,
        lane_path=tmp_path / "worker",
        budget_path="src/proven.py",
    )
    target_id = seed_target(
        test_db,
        item_id=item_id,
        path="src/proven.py",
    )
    claim_id = seed_item_claim(
        test_db,
        item_id=item_id,
        target_ids=(target_id,),
        state="planned",
    )
    test_db.execute("DROP TABLE path_claim_task_bindings")
    test_db.commit()

    apply(test_db)
    invariants(test_db)
    apply(test_db)
    invariants(test_db)

    assert test_db.execute(
        "SELECT claim_id, epic_id, task_num FROM path_claim_task_bindings"
    ).fetchall() == [(claim_id, item_id, 1)]


def test_apply_refuses_live_claim_targets_absent_from_task_budgets(
    test_db,
    tmp_path,
) -> None:
    item_id = seed_epic(test_db, item_id=21305)
    seed_worker_task(
        test_db,
        item_id=item_id,
        task_num=1,
        lane_path=tmp_path / "worker",
        budget_path="src/proven.py",
    )
    proven = seed_target(
        test_db,
        item_id=item_id,
        path="src/proven.py",
    )
    unrelated = seed_target(
        test_db,
        item_id=item_id,
        path="src/unmapped.py",
    )
    seed_item_claim(
        test_db,
        item_id=item_id,
        target_ids=(proven, unrelated),
        state="planned",
    )
    test_db.execute("DROP TABLE path_claim_task_bindings")
    test_db.commit()

    with pytest.raises(
        UnsafeTaskBindingBackfill,
        match="absent from every persisted task budget",
    ):
        apply(test_db)

    assert not _table_exists(test_db, "path_claim_task_bindings")


def test_apply_allows_intake_item_with_no_generated_tasks(test_db) -> None:
    item_id = seed_epic(test_db, item_id=21306, status="refined-idea")
    test_db.execute("DROP TABLE path_claim_task_bindings")
    test_db.commit()

    apply(test_db)
    invariants(test_db)

    assert _table_exists(test_db, "path_claim_task_bindings")
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM path_claim_task_bindings WHERE epic_id = %s",
            (item_id,),
        ).fetchone()[0]
        == 0
    )
