"""Real-repository scaffolding for the landed-lane retirement tests.

Every proof the retirement relies on is a git fact — what ``origin/main``
contains after a fetch, whether a worktree is clean, whether a branch still
exists — so these build an actual repository with an actual remote. A fake that
answers those questions cannot fail the way git does.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace


BRANCH = "YOK-CLEANUP"


def _git(path: Path, *args: str, check: bool = True):
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _run_git(args, *, cwd=None, capture=False):
    """The engine's git-runner shape, backed by a real subprocess."""
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        check=False,
        capture_output=True,
        text=True,
    )


def build_landed_lane(tmp_path: Path):
    """A repo whose lane branch is merged and pushed, with a live worktree."""
    origin = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(origin)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    nested = repo / "webapp"
    nested.mkdir()
    (nested / ".gitignore").write_text("generated/\n", encoding="utf-8")
    _git(repo, "add", "README.md", "webapp/.gitignore")
    _git(repo, "commit", "-m", "base")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-u", "origin", "main")

    worktree = repo / ".worktrees" / BRANCH
    _git(repo, "worktree", "add", "-b", BRANCH, str(worktree))
    (worktree / "lane.txt").write_text("lane work\n", encoding="utf-8")
    _git(worktree, "add", "lane.txt")
    _git(worktree, "commit", "-m", "lane work")
    _git(repo, "push", "origin", BRANCH)
    return SimpleNamespace(origin=origin, repo=repo, worktree=worktree)


def _land_on_main(repo: Path) -> None:
    """Merge the lane on the remote, the way a merge queue would."""
    _git(repo, "fetch", "origin", BRANCH)
    _git(repo, "merge", "--no-ff", "-m", f"merge {BRANCH}", BRANCH)
    _git(repo, "push", "origin", "main")
    _git(repo, "update-ref", "refs/heads/main", "HEAD~1")


def _remote_branches(repo: Path) -> list[str]:
    listed = _git(repo, "ls-remote", "--heads", "origin")
    return [line.split()[1] for line in listed.stdout.splitlines() if line]


def _local_branches(repo: Path) -> list[str]:
    listed = _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    return listed.stdout.split()


__all__ = [
    "BRANCH",
    "build_landed_lane",
    "_git",
    "_land_on_main",
    "_local_branches",
    "_remote_branches",
    "_run_git",
]
