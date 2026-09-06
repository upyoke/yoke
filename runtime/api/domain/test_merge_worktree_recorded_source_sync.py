"""Worktree-safety regressions for the merge engine's recorded-source bind.

``bind_recorded_source`` reconciles a lane branch with its control-plane
recorded identity; when that branch is checked out in a linked worktree,
reconciling it needs ref, index, and files to move together, so this module
owns the coverage for that hazard -- unlike
``test_standalone_item_merge_recorded_head.py``, whose fixture never checks
the lane out anywhere.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext
from yoke_core.engines.merge_worktree_recorded_source import (
    bind_recorded_source,
    record_lane_head_after_merge,
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repo_with_lane_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """A repo with ``lane`` checked out in its own linked worktree."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "base.txt").write_text("base\n")
    _git(repo, "add", "base.txt")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "branch", "lane")
    lane_dir = tmp_path / "lane-worktree"
    _git(repo, "worktree", "add", str(lane_dir), "lane")
    return repo, lane_dir


def test_forward_rebind_syncs_a_clean_checked_out_worktree(tmp_path: Path) -> None:
    """The original recovery this function exists for, now worktree-safe."""
    repo, lane_dir = _repo_with_lane_worktree(tmp_path)
    stale = _git(repo, "rev-parse", "lane")
    # The recorded commit exists in the object store (pushed from elsewhere)
    # but the local lane ref and its checked-out worktree have not caught
    # up to it yet.
    _git(repo, "checkout", "-q", "-b", "elsewhere", "main")
    (repo / "feature.txt").write_text("recorded work\n")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-q", "-m", "feature")
    recorded = _git(repo, "rev-parse", "elsewhere")
    _git(repo, "checkout", "-q", "main")
    context = MergeContext(
        args=MergeArgs(branch="lane", source_sha=recorded),
        repo_root=str(repo),
        worktree_path=str(lane_dir),
    )

    assert bind_recorded_source(context, stale) == ""

    assert _git(repo, "rev-parse", "lane") == recorded
    assert _git(lane_dir, "rev-parse", "HEAD") == recorded
    assert (lane_dir / "feature.txt").read_text() == "recorded work\n"
    assert _git(lane_dir, "status", "--porcelain") == ""


def test_forward_rebind_refuses_when_checked_out_worktree_is_dirty(
    tmp_path: Path,
) -> None:
    """Genuine local work the fast-forward would overwrite must survive.

    ``git merge --ff-only`` itself is unaffected by unrelated dirt (an
    untracked file the incoming tree never touches) -- it only refuses when
    proceeding would actually clobber something, so the fixture needs a
    genuine collision: an untracked ``feature.txt`` in the lane, the same
    path the recorded commit introduces.
    """
    repo, lane_dir = _repo_with_lane_worktree(tmp_path)
    stale = _git(repo, "rev-parse", "lane")
    _git(repo, "checkout", "-q", "-b", "elsewhere", "main")
    (repo / "feature.txt").write_text("recorded work\n")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-q", "-m", "feature")
    recorded = _git(repo, "rev-parse", "elsewhere")
    _git(repo, "checkout", "-q", "main")
    (lane_dir / "feature.txt").write_text("genuine uncommitted local work\n")
    context = MergeContext(
        args=MergeArgs(branch="lane", source_sha=recorded),
        repo_root=str(repo),
        worktree_path=str(lane_dir),
    )

    error = bind_recorded_source(context, stale)

    assert "uncommitted" in error
    assert _git(repo, "rev-parse", "lane") == stale
    assert (lane_dir / "feature.txt").read_text() == "genuine uncommitted local work\n"


def test_interrupted_merge_retry_preserves_progress_and_worktree(
    tmp_path: Path, monkeypatch,
) -> None:
    """Reproduces the interrupted-merge/retry incident end to end.

    Engine run #1 advances HEAD and persists it through
    ``record_lane_head_after_merge``. More engine-owned progress lands
    but the process is interrupted before the next persist call. A retry
    resolving ``source_sha`` from that now-stale record must recognize the
    branch as a proven continuation, leave it and its checked-out worktree
    completely untouched, and preserve unrelated uncommitted work sitting
    there. The registered ``project.snapshot.sync`` write itself is
    covered elsewhere (``test_item_worktree_head_recording.py``); this
    verifies the engine calls it correctly, head-only, for the checked-out
    lane.
    """
    import yoke_cli.commands.adapters.project_snapshot as project_snapshot

    repo, lane_dir = _repo_with_lane_worktree(tmp_path)
    persisted: list[dict] = []
    monkeypatch.setattr(
        project_snapshot,
        "sync_local_snapshot_for_write",
        lambda **kwargs: persisted.append(kwargs) or {"status": "ok"},
    )

    (lane_dir / "feature.txt").write_text("feature work\n")
    _git(lane_dir, "add", "feature.txt")
    _git(lane_dir, "commit", "-q", "-m", "feature")
    first = _git(lane_dir, "rev-parse", "HEAD")
    record_lane_head_after_merge(MergeContext(
        args=MergeArgs(branch="lane"),
        repo_root=str(repo),
        worktree_path=str(lane_dir),
        project="yoke",
    ))
    assert persisted == [{
        "project": "yoke",
        "repo_root": str(lane_dir),
        "integration_target": None,
        "session_id": None,
        "head_only": True,
    }]

    (lane_dir / "more.txt").write_text("more work\n")
    _git(lane_dir, "add", "more.txt")
    _git(lane_dir, "commit", "-q", "-m", "more work")
    second = _git(lane_dir, "rev-parse", "HEAD")
    (lane_dir / "scratch.txt").write_text("genuine uncommitted local work\n")

    retry_context = MergeContext(
        args=MergeArgs(branch="lane", source_sha=first),
        repo_root=str(repo),
        worktree_path=str(lane_dir),
        project="yoke",
    )

    assert bind_recorded_source(retry_context, second) == ""

    assert _git(repo, "rev-parse", "lane") == second
    assert _git(lane_dir, "rev-parse", "HEAD") == second
    assert (lane_dir / "more.txt").read_text() == "more work\n"
    assert (lane_dir / "scratch.txt").read_text() == "genuine uncommitted local work\n"
