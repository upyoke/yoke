"""Doctor reports landed lanes without enforcing a worktree limit."""

from __future__ import annotations

import subprocess
from pathlib import Path

from yoke_core.domain import worktree_maintenance


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _commit(repo: Path, message: str) -> None:
    # A real change: git's patch-equivalence proof treats an empty commit as
    # already carried by any base.
    (repo / f"{message.replace(' ', '-')}.txt").write_text(message)
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", message)


def _repo_with_landed_and_unmerged_lane(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _commit(repo, "base")
    _git(repo, "worktree", "add", "-b", "ITEM-7", str(repo / ".worktrees" / "ITEM-7"))
    _git(repo, "worktree", "add", "-b", "ITEM-8", str(repo / ".worktrees" / "ITEM-8"))
    _commit(repo / ".worktrees" / "ITEM-7", "landed work")
    _git(repo, "merge", "--ff-only", "ITEM-7")
    _commit(repo / ".worktrees" / "ITEM-8", "unlanded work")
    return repo


def test_doctor_lists_landed_lanes_apart(tmp_path: Path) -> None:
    repo = _repo_with_landed_and_unmerged_lane(tmp_path)

    def run_git(args, *, cwd=None, capture=True):
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True
        )

    note = worktree_maintenance.landed_lanes_note(
        run_git, str(repo), [("ITEM-7", "ITEM-7", "main"), ("ITEM-8", "ITEM-8", "main")]
    )

    assert note == ("- 1 landed lane(s) await release close-out: ITEM-7")
