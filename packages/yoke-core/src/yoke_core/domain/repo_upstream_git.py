"""Git mechanics for reading and advancing a checkout's default branch.

The freshness policy — what a comparison means and what to tell the caller
— lives in :mod:`yoke_core.domain.repo_upstream_freshness`. This module is
only the git side of it: naming the remote and branch from git's own
records rather than assuming either, reading the comparison, and advancing
a local branch by a fast-forward that can lose nothing.
"""

from __future__ import annotations

import subprocess
from typing import Tuple

FETCH_TIMEOUT_SECONDS = 120
READ_TIMEOUT_SECONDS = 30


def git(
    repo_root: str,
    *args: str,
    timeout: int = READ_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess:
    """Run one git command in ``repo_root`` with the credential it needs."""
    from yoke_cli.config import credentialed_git

    return credentialed_git.run(["-C", repo_root, *args], timeout=timeout)


def out(result: subprocess.CompletedProcess) -> str:
    return (result.stdout or "").strip()


def reason(result: subprocess.CompletedProcess) -> str:
    """Return git's own last word on a failure, never an empty diagnosis."""
    text = f"{result.stderr or ''}\n{result.stdout or ''}"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else "git reported no detail"


def resolve_remote(repo_root: str, base_branch: str = "") -> Tuple[str, int]:
    """Return the remote tracking ``base_branch`` and how many are configured.

    The name is read from git's own records — the branch's tracking remote,
    then the push default, then the sole configured remote. With several
    remotes and nothing recorded, the name comes back empty rather than
    guessed.
    """
    listed = git(repo_root, "remote")
    names = out(listed).split() if listed.returncode == 0 else []
    if base_branch:
        tracked = git(repo_root, "config", "--get", f"branch.{base_branch}.remote")
        if tracked.returncode == 0 and out(tracked):
            return out(tracked), len(names)
    pushed = git(repo_root, "config", "--get", "remote.pushDefault")
    if pushed.returncode == 0 and out(pushed):
        return out(pushed), len(names)
    return (names[0] if len(names) == 1 else ""), len(names)


def resolve_base_branch(repo_root: str, remote: str) -> str:
    """Return the branch ``remote`` publishes as its default, or empty.

    There is deliberately no fall back to whatever branch happens to be
    checked out: a session standing on a feature lane would name that lane
    as the project's default and prepare every later lane from it.
    """
    if not remote:
        return ""
    head = git(repo_root, "symbolic-ref", "--short", f"refs/remotes/{remote}/HEAD")
    if head.returncode != 0 or not out(head):
        return ""
    named = out(head)
    prefix = f"{remote}/"
    return named[len(prefix):] if named.startswith(prefix) else named


def branch_checkout_path(repo_root: str, base_branch: str) -> str:
    """Return the worktree path holding ``base_branch``, or empty for none."""
    listed = git(repo_root, "worktree", "list", "--porcelain")
    if listed.returncode != 0:
        return ""
    path = ""
    for line in (listed.stdout or "").splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):].strip()
        elif line.strip() == f"branch refs/heads/{base_branch}":
            return path
    return ""


def tracking_ref(remote: str, base_branch: str) -> str:
    return f"refs/remotes/{remote}/{base_branch}"


def fetch_branch(
    repo_root: str, remote: str, base_branch: str
) -> subprocess.CompletedProcess:
    """Update only the remote-tracking ref, which no local work lives on."""
    return git(
        repo_root,
        "fetch",
        "--no-tags",
        remote,
        f"+refs/heads/{base_branch}:{tracking_ref(remote, base_branch)}",
        timeout=FETCH_TIMEOUT_SECONDS,
    )


def count_ahead_behind(
    repo_root: str, local_sha: str, upstream_ref: str
) -> Tuple[bool, int, int, str]:
    """Return ``(read, ahead, behind, detail)`` for local versus upstream."""
    counted = git(
        repo_root, "rev-list", "--left-right", "--count", f"{local_sha}...{upstream_ref}"
    )
    if counted.returncode != 0:
        return False, 0, 0, reason(counted)
    fields = out(counted).split()
    if len(fields) != 2:
        return False, 0, 0, f"unreadable rev-list output {out(counted)!r}"
    return True, int(fields[0]), int(fields[1]), ""


def fast_forward(
    repo_root: str, base_branch: str, local_sha: str, upstream_sha: str
) -> Tuple[bool, str]:
    """Advance ``base_branch`` to a revision that already contains it.

    A checkout sitting on the branch merges, so its working tree moves with
    the ref and git refuses rather than overwrite an uncommitted change. A
    branch checked out somewhere else is left alone entirely — moving its
    ref from here would leave that tree reporting reversions it never made.
    Anywhere else the ref moves under a compare-and-swap on the revision
    this evaluation actually read.
    """
    holder = branch_checkout_path(repo_root, base_branch)
    if holder and holder.rstrip("/") == repo_root.rstrip("/"):
        merged = git(repo_root, "merge", "--ff-only", upstream_sha)
        return (merged.returncode == 0), reason(merged)
    if holder:
        return False, f"{base_branch} is checked out at {holder}"
    moved = git(
        repo_root, "update-ref", f"refs/heads/{base_branch}", upstream_sha, local_sha
    )
    return (moved.returncode == 0), reason(moved)


__all__ = [
    "FETCH_TIMEOUT_SECONDS",
    "READ_TIMEOUT_SECONDS",
    "branch_checkout_path",
    "count_ahead_behind",
    "fast_forward",
    "fetch_branch",
    "git",
    "out",
    "reason",
    "resolve_base_branch",
    "resolve_remote",
    "tracking_ref",
]
