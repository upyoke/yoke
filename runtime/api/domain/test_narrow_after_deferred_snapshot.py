"""Path-claim narrowing while a large path snapshot upload is deferred.

The chunked sync keeps a large file inventory off the write path and
uploads it on a later sync. Narrowing does not read that inventory — it
reads the lane's synced head — so the deferral must not make narrowing
unverifiable.
"""

from __future__ import annotations

from contextlib import nullcontext

import pytest

from yoke_contracts.path_snapshot_chunks import (
    PathSnapshotChunkMetadata,
    PathSnapshotChunkSyncPayload,
)

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.item_worktrees import record_item_worktree
from yoke_core.domain.path_claims_boundary import (
    BoundaryCheckError,
    BoundaryCheckStatus,
)
from yoke_core.domain.path_claims_narrow_boundary import check_narrow_boundary
from yoke_core.domain.project_snapshot_chunk_uploads import sync_chunk
from yoke_core.domain.workflow_behavior import LANE_IMPLEMENTATION

_ITEM_ID = 9631
_LANE_PATH = "/tmp/yoke-lane-9631"
_HEAD = "d" * 40
_KEPT = "src/kept.py"


@pytest.fixture
def lane(test_db, monkeypatch):
    insert_item(test_db, id=_ITEM_ID, workflow_id="dash")
    record_item_worktree(
        test_db,
        item_id=_ITEM_ID,
        branch=f"YOK-{_ITEM_ID}",
        path=_LANE_PATH,
        lane_role=LANE_IMPLEMENTATION,
    )
    test_db.commit()
    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect",
        lambda *_a, **_k: nullcontext(test_db),
    )
    return test_db


def _claim() -> dict:
    return {
        "id": 771,
        "integration_target": "main",
        "owner_item_id": _ITEM_ID,
        "activated_at": "2026-08-25T00:00:00Z",
        "base_commit_sha": "e" * 40,
    }


def _evidence() -> dict:
    return {
        "repo_root": _LANE_PATH,
        "head_sha": _HEAD,
        "integration_target": "main",
        "touched_paths": [_KEPT],
        "uncommitted_paths": [],
        "rename_pairs": [],
    }


def _begin_head_upload(*, file_count: int, chunk_count: int, hook_mode: bool):
    return sync_chunk(
        "yoke",
        PathSnapshotChunkSyncPayload(
            project_id="yoke",
            repo_root=_LANE_PATH,
            upload_id="upload-9631",
            operation="begin",
            snapshot=PathSnapshotChunkMetadata(
                ref="HEAD",
                commit_sha=_HEAD,
                file_count=file_count,
                chunk_count=chunk_count,
            ),
            hook_mode=hook_mode,
        ),
        _unused_sync_payload,
    )


def _unused_sync_payload(*_args, **_kwargs):
    raise AssertionError("a deferred upload never finalizes its inventory")


def test_narrowing_refuses_before_any_lane_head_is_synced(lane) -> None:
    with pytest.raises(BoundaryCheckError) as refusal:
        check_narrow_boundary(
            lane,
            claim=_claim(),
            project_id=1,
            candidate_paths=[_KEPT],
            boundary_evidence=_evidence(),
        )

    # The refusal names the exact command that binds the lane head.
    assert "yoke project snapshot sync" in str(refusal.value)
    assert _LANE_PATH in str(refusal.value)


def test_deferred_inventory_still_binds_the_lane_head(lane) -> None:
    result = _begin_head_upload(file_count=4000, chunk_count=6, hook_mode=True)

    assert result["status"] == "chunk_upload_started"
    assert result["lane_head_recorded"] is True
    assert lane.execute(
        "SELECT commit_sha FROM item_worktrees WHERE item_id = %s",
        (_ITEM_ID,),
    ).fetchone()[0] == _HEAD


def test_narrowing_succeeds_while_the_inventory_is_deferred(lane) -> None:
    _begin_head_upload(file_count=4000, chunk_count=6, hook_mode=True)
    sync_chunk(
        None,
        PathSnapshotChunkSyncPayload(
            upload_id="upload-9631", operation="abort",
        ),
        _unused_sync_payload,
    )

    result = check_narrow_boundary(
        lane,
        claim=_claim(),
        project_id=1,
        candidate_paths=[_KEPT],
        boundary_evidence=_evidence(),
    )

    assert result.status is BoundaryCheckStatus.VALID
    assert result.undeclared_paths == []


def test_reused_inventory_still_binds_the_lane_head(lane, monkeypatch) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.path_snapshot_payload_materializer."
        "find_existing_snapshot_id",
        lambda *_a, **_k: 4242,
    )

    result = _begin_head_upload(file_count=4000, chunk_count=6, hook_mode=False)

    assert result["status"] == "reused"
    assert result["lane_head_recorded"] is True
    assert check_narrow_boundary(
        lane,
        claim=_claim(),
        project_id=1,
        candidate_paths=[_KEPT],
        boundary_evidence=_evidence(),
    ).status is BoundaryCheckStatus.VALID
