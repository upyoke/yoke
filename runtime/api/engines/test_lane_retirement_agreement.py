"""The landing boundary and the machine sweep retire the same lanes.

One lane must not be disposable to the boundary that lands it and precious
to the sweep that revisits it: that disagreement is what leaves a directory
on disk forever, or removes content the other boundary would have kept. So
both readings — what the target already holds, and what is left in the
directory — are exercised here through both entry points.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.api.engines._merge_prune_test_helpers import (
    _Conn,
    _git,
    _install,
    _repo,
)
from yoke_core.domain.terminal_lane_cleanup import cleanup_terminal_item_lanes
from yoke_core.engines.merge_landed_lane_cleanup import prune_landed_lane
from yoke_core.engines.merge_worktree_safe_prune import (
    WorktreeSweep,
    prune_managed_worktrees,
)


def _run_git(args, *, cwd=None, capture=False):
    """The engine's git-runner shape, backed by a real subprocess."""
    return _git(Path(cwd), *args, check=False)


def _lane_commit(repo: Path, worktree: Path, name: str = "lane.txt") -> None:
    (worktree / name).write_text(f"{name}\n", encoding="utf-8")
    _git(worktree, "add", name)
    _git(worktree, "commit", "-m", f"lane {name}")


def _land_rebased(repo: Path, branch: str) -> None:
    """Land the lane's changes the way a rebase or squash merge does.

    Main advances first, so replaying the lane commit onto it produces a
    different commit for the same patch. Exact ancestry reads the lane as
    unmerged afterwards even though origin/main holds every change it made.
    """
    (repo / "meanwhile.txt").write_text("meanwhile\n", encoding="utf-8")
    _git(repo, "add", "meanwhile.txt")
    _git(repo, "commit", "-m", "meanwhile")
    _git(repo, "cherry-pick", branch)
    _git(repo, "push", "origin", "main")


@pytest.fixture()
def rebased_lane(tmp_path: Path):
    """A lane whose change is on origin/main under a different commit."""
    repo, worktree, branch = _repo(tmp_path)
    _lane_commit(repo, worktree)
    _git(repo, "push", "origin", branch)
    _land_rebased(repo, branch)
    return SimpleNamespace(repo=repo, worktree=worktree, branch=branch)


def _remote_branches(repo: Path) -> list[str]:
    listed = _git(repo, "ls-remote", "--heads", "origin")
    return [line.split()[1] for line in listed.stdout.splitlines() if line]


def test_the_landing_boundary_retires_a_rebased_lane(rebased_lane):
    """Every part of the lane goes, including the branch ``-d`` refuses."""
    preserved = prune_landed_lane(
        repo_root=str(rebased_lane.repo),
        branch=rebased_lane.branch,
        target="main",
        run_git=_run_git,
        emit=lambda *_a, **_kw: None,
    )

    assert preserved == ()
    assert not rebased_lane.worktree.exists()
    assert _git(rebased_lane.repo, "branch", "--list", rebased_lane.branch).stdout == ""
    assert f"refs/heads/{rebased_lane.branch}" not in _remote_branches(
        rebased_lane.repo
    )


def test_the_machine_sweep_retires_the_same_rebased_lane(
    rebased_lane, monkeypatch
):
    git_io, lines = _install(
        monkeypatch, rebased_lane.repo, _Conn(rebased_lane.branch)
    )

    sweep = prune_managed_worktrees(
        **git_io, repo_root=str(rebased_lane.repo), target="main"
    )

    assert sweep.preserved == ()
    assert sweep.removed == (str(rebased_lane.worktree.resolve()),)
    assert not rebased_lane.worktree.exists()
    assert _git(rebased_lane.repo, "branch", "--list", rebased_lane.branch).stdout == ""


def test_a_lane_with_unique_work_survives_both_boundaries(
    rebased_lane, monkeypatch
):
    """A commit the target has no equivalent for outranks the landing."""
    _lane_commit(rebased_lane.repo, rebased_lane.worktree, "unique.txt")

    preserved = prune_landed_lane(
        repo_root=str(rebased_lane.repo),
        branch=rebased_lane.branch,
        target="main",
        run_git=_run_git,
        emit=lambda *_a, **_kw: None,
    )
    git_io, lines = _install(
        monkeypatch, rebased_lane.repo, _Conn(rebased_lane.branch)
    )
    sweep = prune_managed_worktrees(
        **git_io, repo_root=str(rebased_lane.repo), target="main"
    )

    assert "no equivalent there" in preserved[0]
    assert [lane.reason for lane in sweep.preserved] == [
        f"worktree branch {rebased_lane.branch} is not merged into "
        f"origin/main and carries 1 commit with no equivalent there"
    ]
    assert rebased_lane.worktree.exists()
    assert (rebased_lane.worktree / "unique.txt").exists()


@pytest.fixture()
def lane_whose_remote_kept_work(rebased_lane, tmp_path: Path):
    """A landed, clean lane whose origin branch holds work that never landed.

    This is the shape a post-merge push leaves: the local side is finished
    and provably retained by the target, while the remote carries commits
    only a person can dispose of.
    """
    scratch = tmp_path / "scratch"
    _git(rebased_lane.repo, "worktree", "add", "--detach", str(scratch),
         rebased_lane.branch)
    (scratch / "remote_only.txt").write_text("remote only\n", encoding="utf-8")
    _git(scratch, "add", "remote_only.txt")
    _git(scratch, "commit", "-m", "pushed after the merge, never landed")
    _git(scratch, "push", "origin", f"HEAD:refs/heads/{rebased_lane.branch}")
    _git(rebased_lane.repo, "worktree", "remove", str(scratch))
    return rebased_lane


def test_the_landing_boundary_retires_a_lane_whose_remote_kept_work(
    lane_whose_remote_kept_work,
):
    """A remote nobody can delete must not pin a finished local lane.

    Retrying cannot turn unmerged remote work into merged work, so treating
    it as a retry left a clean, landed directory on disk for as long as the
    remote existed, re-refusing on every landing.
    """
    lane = lane_whose_remote_kept_work

    preserved = prune_landed_lane(
        repo_root=str(lane.repo),
        branch=lane.branch,
        target="main",
        run_git=_run_git,
        emit=lambda *_a, **_kw: None,
    )

    assert not lane.worktree.exists()
    assert _git(lane.repo, "branch", "--list", lane.branch).stdout == ""
    assert f"refs/heads/{lane.branch}" in _remote_branches(lane.repo)
    assert len(preserved) == 1
    assert f"origin/{lane.branch} kept after its local lane retired" in preserved[0]
    assert f"land origin/{lane.branch} or delete it" in preserved[0]


def test_the_machine_sweep_retires_that_same_lane(
    lane_whose_remote_kept_work, monkeypatch
):
    """The sweep must not keep what the landing boundary retires."""
    lane = lane_whose_remote_kept_work
    git_io, lines = _install(monkeypatch, lane.repo, _Conn(lane.branch))

    sweep = prune_managed_worktrees(
        **git_io, repo_root=str(lane.repo), target="main"
    )

    assert sweep.preserved == ()
    assert sweep.removed == (str(lane.worktree.resolve()),)
    assert not lane.worktree.exists()
    assert f"refs/heads/{lane.branch}" in _remote_branches(lane.repo)
    assert any(
        f"origin/{lane.branch} kept after its local lane retired" in line
        for line in lines
    )


def test_a_remote_that_may_yet_delete_still_preserves_the_whole_lane(rebased_lane):
    """An unproven remote is a genuine retry, so the lane stays put.

    The distinction that matters is whether running again could reach a
    different answer. A refused delete could; unmerged work could not.
    """
    _git(rebased_lane.repo.parent / "origin.git", "config", "receive.denyDeletes",
         "true")

    preserved = prune_landed_lane(
        repo_root=str(rebased_lane.repo),
        branch=rebased_lane.branch,
        target="main",
        run_git=_run_git,
        emit=lambda *_a, **_kw: None,
    )

    assert rebased_lane.worktree.exists()
    assert "preserved so remote cleanup can be retried" in preserved[0]


def test_named_caches_are_disposable_to_both_boundaries(rebased_lane):
    """The landing removes the same residue the sweep would have removed."""
    cache = rebased_lane.worktree / "webapp" / "node_modules" / "pkg" / "index.js"
    cache.parent.mkdir(parents=True)
    cache.write_text("generated\n", encoding="utf-8")

    preserved = prune_landed_lane(
        repo_root=str(rebased_lane.repo),
        branch=rebased_lane.branch,
        target="main",
        run_git=_run_git,
        emit=lambda *_a, **_kw: None,
    )

    assert preserved == ()
    assert not rebased_lane.worktree.exists()


def test_unknown_ignored_content_survives_both_boundaries(
    rebased_lane, monkeypatch
):
    """Ignored says "do not track", never "delete" — on either boundary."""
    protected = rebased_lane.worktree / ".private" / "operator-note"
    protected.parent.mkdir(parents=True)
    protected.write_text("keep me\n", encoding="utf-8")

    preserved = prune_landed_lane(
        repo_root=str(rebased_lane.repo),
        branch=rebased_lane.branch,
        target="main",
        run_git=_run_git,
        emit=lambda *_a, **_kw: None,
    )
    git_io, _lines = _install(
        monkeypatch, rebased_lane.repo, _Conn(rebased_lane.branch)
    )
    sweep = prune_managed_worktrees(
        **git_io, repo_root=str(rebased_lane.repo), target="main"
    )

    assert "unknown ignored files present: .private/" in preserved[0]
    assert [lane.reason for lane in sweep.preserved] == [
        "unknown ignored files present: .private/"
    ]
    assert protected.read_text(encoding="utf-8") == "keep me\n"


def _item(rebased_lane) -> dict:
    return {
        "id": 7,
        "public_ref": "ITEM-7",
        "status": "done",
        "workflow": {"id": "dash", "terminal_stage_ids": ["done", "cancelled"]},
        "project": {"id": 1, "slug": "yoke", "default_branch": "main"},
        "claim": None,
        "worktrees": [
            {"branch": rebased_lane.branch, "path": str(rebased_lane.worktree)}
        ],
    }


def test_a_repeated_close_out_finds_nothing_left_to_say(
    rebased_lane, monkeypatch
):
    """Close-out runs again on an already-retired item without complaining.

    Re-entry is the retry for a refused retirement, so it must be quiet when
    there is nothing left: a lane whose branch and directory are both gone
    is skipped rather than reported as preserved for want of a branch to
    prove anything about.
    """
    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        lambda **_kw: SimpleNamespace(success=True, result={}, error=None),
    )
    item = _item(rebased_lane)

    def close_out():
        return cleanup_terminal_item_lanes(
            item,
            target_status="done",
            repo_root=rebased_lane.repo,
            target_branch="main",
            emit=lambda *_a, **_kw: None,
            sweep=lambda **_kw: WorktreeSweep(),
        )

    first = close_out()
    second = close_out()

    assert first.warnings == ()
    assert second.warnings == ()
    assert not rebased_lane.worktree.exists()
