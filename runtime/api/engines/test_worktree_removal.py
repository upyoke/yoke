"""Lane removal survives interruption and never runs under a shrinking deadline.

A doctor ``--fix`` run killed mid ``git worktree remove`` once left a
registered, half-deleted tree that every later read preserved as dirty work.
These tests drive real git: a removal is atomic through a tombstone, a leftover
tombstone is finished by the next sweep, a check deadline cannot cut a removal
short, a short budget defers instead of starting one, and a deletion-only tree
on a landed branch is completed as the interrupted removal it is.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from yoke_contracts import doctor_budget
from yoke_core.engines import worktree_removal
from yoke_core.engines.merge_landed_lane_cleanup import prune_landed_lane
from yoke_core.engines.merge_worktree_cleanliness import assess_lane_residue
from yoke_core.engines.worktree_removal import (
    finish_tombstones,
    remove_worktree,
    tombstones,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def _run_git(command, *, cwd=None, capture=True):
    return subprocess.run(
        ["git", *command], cwd=cwd, capture_output=True, text=True, check=False
    )


@pytest.fixture
def lane(tmp_path: Path) -> tuple[Path, Path]:
    """A repository with one landed lane holding tracked files."""
    repo = tmp_path / "repo"
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(repo)],
        check=True,
        capture_output=True,
    )
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    for name in ("a.txt", "b.txt", "c.txt"):
        (repo / name).write_text(f"{name}\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    path = repo / ".worktrees" / "YOK-1"
    _git(repo, "worktree", "add", "-b", "YOK-1", str(path), "main")
    return repo, path


def _registered(repo: Path) -> str:
    return _git(repo, "worktree", "list", "--porcelain")


def test_removal_is_complete_and_leaves_no_tombstone(lane):
    repo, path = lane

    result = remove_worktree(repo, path)

    assert result.removed and not result.reason
    assert not path.exists()
    assert str(path) not in _registered(repo)
    assert tombstones(repo) == []


def test_a_tombstone_left_by_an_interruption_is_finished_by_the_next_sweep(
    lane, monkeypatch
):
    repo, path = lane
    monkeypatch.setattr(
        worktree_removal.shutil,
        "rmtree",
        lambda _path: (_ for _ in ()).throw(OSError("interrupted")),
    )

    first = remove_worktree(repo, path)

    # Git no longer registers the lane; only an inert tombstone remains.
    assert first.removed and "not yet deleted" in first.reason
    assert str(path) not in _registered(repo)
    [leftover] = tombstones(repo)
    monkeypatch.undo()

    assert [r.removed for r in finish_tombstones(repo)] == [True]
    assert not leftover.exists()


def test_a_kill_between_rename_and_prune_is_finished_by_the_next_sweep(lane):
    repo, path = lane
    path.rename(path.parent / f"{worktree_removal.TOMBSTONE_PREFIX}YOK-1-dead")

    [result] = finish_tombstones(repo)

    assert result.removed
    assert "YOK-1" not in _registered(repo)
    assert tombstones(repo) == []


def test_an_expiring_check_deadline_cannot_cut_a_removal_short(lane, monkeypatch):
    repo, path = lane
    monkeypatch.setattr(doctor_budget, "CHECK_BUDGET_S", 0.2)
    monkeypatch.setattr(worktree_removal, "REMOVAL_MIN_BUDGET_S", 0.05)
    real_git = worktree_removal._git

    def slow_prune(repo_root, *args):
        if "prune" in args:
            time.sleep(0.5)
        return real_git(repo_root, *args)

    monkeypatch.setattr(worktree_removal, "_git", slow_prune)

    # Removal time stays off the check clock, so the verdicts after it survive.
    with doctor_budget.check_budget():
        result = remove_worktree(repo, path)
        left = doctor_budget.remaining_budget()

    assert result.removed
    assert left is not None and left > 0.05
    assert not path.exists()
    assert str(path) not in _registered(repo)
    assert tombstones(repo) == []


def test_too_little_budget_defers_the_removal_untouched(lane, monkeypatch):
    repo, path = lane
    monkeypatch.setattr(worktree_removal, "remaining_budget", lambda: 3.0)

    result = remove_worktree(repo, path)

    assert not result.removed
    assert "removal deferred" in result.reason and "--fix" in result.reason
    assert path.is_dir() and str(path) in _registered(repo)


def test_a_deletion_only_landed_lane_is_completed_as_an_interrupted_removal(lane):
    repo, path = lane
    (path / "a.txt").unlink()
    (path / "b.txt").unlink()

    residue = assess_lane_residue(_run_git, path)
    assert residue.interrupted_removal
    assert residue.reason.startswith("interrupted removal: 2 tracked files")

    preserved = prune_landed_lane(
        repo_root=str(repo),
        branch="YOK-1",
        target="main",
        run_git=_run_git,
        emit=lambda *_a, **_kw: None,
    )

    assert preserved == ()
    assert not path.exists()
    assert _git(repo, "branch", "--list", "YOK-1").strip() == ""


def test_a_deletion_beside_new_work_is_still_preserved(lane):
    repo, path = lane
    (path / "a.txt").unlink()
    (path / "notes.txt").write_text("keep\n", encoding="utf-8")

    residue = assess_lane_residue(_run_git, path)
    assert not residue.interrupted_removal

    preserved = prune_landed_lane(
        repo_root=str(repo),
        branch="YOK-1",
        target="main",
        run_git=_run_git,
        emit=lambda *_a, **_kw: None,
    )

    assert preserved and "notes.txt" in preserved[0]
    assert (path / "notes.txt").read_text(encoding="utf-8") == "keep\n"
