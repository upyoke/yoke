"""What the checkout can say about one standalone item branch.

The reads a standalone merge depends on, isolated from the boundary that
sequences them, because their answers change as the merge proceeds: the
branch ref disappears with the engine's cleanup and ``changed_files``
collapses to nothing the moment the branch lands. Callers that need those
facts after either point read them from the recorded receipt instead
(:mod:`yoke_core.domain.standalone_item_merge_receipt`).

Every read fails soft — a git error reads as "the checkout does not say so"
rather than raising — so the boundary decides what an absent answer means.
"""

from __future__ import annotations

import subprocess


def _git(repo_root: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def git_out(repo_root: str, *args: str) -> str:
    """Trimmed stdout for a git read; empty when the command fails."""
    result = _git(repo_root, *args)
    return result.stdout.strip() if result.returncode == 0 else ""


def branch_exists(repo_root: str, branch: str) -> bool:
    return _git(
        repo_root, "rev-parse", "--verify", f"refs/heads/{branch}"
    ).returncode == 0


def head_of(repo_root: str, branch: str) -> str:
    """The commit a local branch points at; empty when it cannot be read."""
    return git_out(repo_root, "rev-parse", f"refs/heads/{branch}")


def is_ancestor(repo_root: str, commit: str, target: str) -> bool:
    """Whether ``target`` already contains ``commit``."""
    return _git(
        repo_root, "merge-base", "--is-ancestor", commit, target
    ).returncode == 0


def changed_files(repo_root: str, branch: str, target: str) -> tuple[str, ...]:
    """Files the branch changed relative to where it left the base branch.

    Empty once ``target`` contains the branch: the merge base becomes the
    branch tip itself and there is nothing left to diff against.
    """
    base = git_out(repo_root, "merge-base", target, branch)
    if not base:
        return ()
    listing = git_out(repo_root, "diff", "--name-only", base, branch)
    return tuple(line.strip() for line in listing.splitlines() if line.strip())


def has_remote(repo_root: str) -> bool:
    return bool(git_out(repo_root, "remote"))


def publish(repo_root: str, target: str) -> tuple[bool, str]:
    """Push the merged base branch. A failure never unwinds the merge."""
    if not has_remote(repo_root):
        return False, ""
    pushed = _git(repo_root, "push", "origin", target)
    if pushed.returncode == 0:
        return True, ""
    detail = (pushed.stderr or pushed.stdout or "").strip()
    return False, (
        f"merge landed locally but publishing '{target}' failed: {detail}"
    )


__all__ = [
    "branch_exists",
    "changed_files",
    "git_out",
    "head_of",
    "has_remote",
    "is_ancestor",
    "publish",
]
