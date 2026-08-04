"""Committed-head recording for active item worktree lanes."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from yoke_contracts.path_snapshot import (
    PathSnapshotPayload,
    PathSnapshotSyncPayload,
)

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.handlers import project_snapshot_sync
from yoke_core.domain.item_worktree_head import record_head_for_checkout
from yoke_core.domain.item_worktrees import record_item_worktree
from yoke_core.domain.workflow_behavior import LANE_IMPLEMENTATION


def _lane(test_db, *, item_id: int, path: str) -> None:
    insert_item(test_db, id=item_id, workflow_id="issue")
    record_item_worktree(
        test_db,
        item_id=item_id,
        branch=f"YOK-{item_id}",
        path=path,
        lane_role=LANE_IMPLEMENTATION,
    )
    test_db.commit()


def test_records_the_head_for_the_exact_active_checkout(test_db) -> None:
    _lane(test_db, item_id=941, path="/tmp/yoke-941")

    lane_id = record_head_for_checkout(
        test_db,
        project_id=1,
        checkout_path="/tmp/yoke-941",
        commit_sha="a" * 40,
    )

    row = test_db.execute(
        "SELECT id, commit_sha FROM item_worktrees WHERE item_id = 941"
    ).fetchone()
    assert lane_id == row[0]
    assert row[1] == "a" * 40


def test_head_snapshot_advances_the_registered_lane(
    test_db, monkeypatch,
) -> None:
    _lane(test_db, item_id=942, path="/tmp/yoke-942")
    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect",
        lambda *_a, **_k: nullcontext(test_db),
    )
    monkeypatch.setattr(
        "yoke_core.domain.path_snapshot_payload_materializer."
        "materialize_snapshot_payload",
        lambda *_a, **_k: SimpleNamespace(
            status="reused", snapshot_id=1, ref="HEAD",
            commit_sha="b" * 40, entry_count=0, symlink_count=0,
        ),
    )
    payload = PathSnapshotSyncPayload(
        project_id="yoke",
        repo_root="/tmp/yoke-942",
        hook_mode=True,
        snapshots=[
            PathSnapshotPayload(
                ref="HEAD",
                commit_sha="b" * 40,
                files=[],
            )
        ],
    )

    result = project_snapshot_sync._sync("yoke", payload)

    assert result["snapshots"][0]["lane_head_recorded"] is True
    assert test_db.execute(
        "SELECT commit_sha FROM item_worktrees WHERE item_id = 942"
    ).fetchone()[0] == "b" * 40


def test_non_lane_snapshot_is_a_no_op(test_db) -> None:
    assert record_head_for_checkout(
        test_db,
        project_id=1,
        checkout_path="/tmp/not-a-lane",
        commit_sha="c" * 40,
    ) is None
