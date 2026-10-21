"""Snapshot sync refreshes HEAD-derived project context only when HEAD moves."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from runtime.api.domain._path_snapshots_test_helpers import path_snapshot_db
from yoke_core.domain import project_snapshot_head_refresh as head_refresh
from yoke_core.domain.handlers import project_snapshot_sync as handler


def _sync(commit_sha: str) -> dict:
    outcome = handler.handle_project_snapshot_sync(
        FunctionCallRequest(
            function="project.snapshot.sync",
            actor=ActorContext(session_id="test-session"),
            target=TargetRef(kind="global", project_id="demo"),
            payload={
                "project_id": "demo",
                "snapshots": [
                    {
                        "ref": "HEAD",
                        "commit_sha": commit_sha,
                        "files": [{"path": "README.md", "line_count": 1}],
                    }
                ],
            },
        )
    )
    assert outcome.primary_success is True, outcome.error
    return outcome.result_payload


@pytest.fixture
def side_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Count each refresh the sync starts."""
    calls: list[str] = []

    def record(name: str, answer):
        def call(*_args, **_kwargs):
            calls.append(name)
            return answer

        return call

    for name, answer in (
        ("refresh_architecture_context", None),
        ("refresh_render_relationship_context", {"status": "ok", "written": 0}),
        ("converge_derived_facts", {"facts": 0}),
    ):
        monkeypatch.setattr(head_refresh, name, record(name, answer))
    repo = tmp_path / "repo"
    repo.mkdir()
    with path_snapshot_db(tmp_path, repo):
        yield calls


def test_a_repeated_head_skips_the_side_work(side_work: list[str]) -> None:
    _sync("a" * 40)
    side_work.clear()

    repeated = _sync("a" * 40)

    assert side_work == []
    assert repeated["snapshots"][0]["status"] == "reused"
    assert repeated["render_relationship_refresh"] is None
    assert repeated["derived_facts"] is None


def test_a_moved_head_runs_the_side_work(side_work: list[str]) -> None:
    _sync("a" * 40)
    side_work.clear()

    moved = _sync("b" * 40)

    assert side_work == [
        "refresh_architecture_context",
        "refresh_render_relationship_context",
        "converge_derived_facts",
    ]
    assert moved["render_relationship_refresh"] == {"status": "ok", "written": 0}
    assert moved["derived_facts"] == {"facts": 0}


def test_returning_to_an_older_head_runs_the_side_work(side_work: list[str]) -> None:
    _sync("a" * 40)
    _sync("b" * 40)
    side_work.clear()

    _sync("a" * 40)

    assert "refresh_architecture_context" in side_work


@pytest.mark.parametrize("already_stored", [True, False])
def test_chunk_finalize_preserves_head_refresh_guard(side_work, already_stored):
    from yoke_contracts.path_snapshot_chunks import PathSnapshotChunkSyncPayload
    from yoke_core.domain import project_snapshot_chunk_uploads as chunks

    _sync("a" * 40)
    chunks.sync_chunk("demo", PathSnapshotChunkSyncPayload(
        upload_id="repeat", operation="begin",
        snapshot={"ref": "HEAD", "commit_sha": "b" * 40,
                  "file_count": 1, "chunk_count": 1},
    ), handler._sync)
    chunks.sync_chunk("demo", PathSnapshotChunkSyncPayload(
        upload_id="repeat", operation="append", chunk_index=0,
        files=[{"path": "README.md", "line_count": 1}],
    ), handler._sync)
    if already_stored:
        # A concurrent upload may store the same HEAD before this finalizes.
        _sync("b" * 40)
    side_work.clear()
    result = chunks.sync_chunk("demo", PathSnapshotChunkSyncPayload(
        upload_id="repeat", operation="finalize",
    ), handler._sync)
    assert result["status"] == "chunk_upload_finalized"
    assert bool(side_work) is not already_stored
