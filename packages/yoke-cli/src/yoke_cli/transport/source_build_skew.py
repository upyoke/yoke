"""Comparing a source checkout against the build a server is running.

The version handshake compares distribution versions, which a source
checkout does not have — :func:`local_handshake_version` returns ``""``
there on purpose, so the comparison disables itself in exactly the
environment where drift is continuous rather than occasional.

Distribution versions are also the wrong axis for that environment. They
move once per release; a checkout moves once per commit. Two sides can
advertise the same version string and still be different code, so a
version-equal answer is not evidence of agreement for a checkout.

The commit is the axis that moves, and the server already advertises one:
its health payload carries the build it was cut from. Comparing that against
the checkout's ``HEAD`` answers the question the version comparison cannot,
using git as the authority rather than inferring from two strings.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

#: Relationships between a local checkout and a server's build. ``UNKNOWN``
#: is a real answer and never collapses into ``EQUAL``: not knowing whether
#: you are current is the state most likely to be skewed, and reporting it
#: as agreement restores the silence this module exists to remove.
AHEAD = "ahead"
BEHIND = "behind"
DIVERGED = "diverged"
EQUAL = "equal"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class BuildComparison:
    """How a local checkout relates to the build a server reports."""

    relationship: str
    local_head: str = ""
    server_build: str = ""
    ahead_by: int = 0
    behind_by: int = 0
    reason: str = ""

    @property
    def differs(self) -> bool:
        return self.relationship in (AHEAD, BEHIND, DIVERGED)


@dataclass(frozen=True)
class OriginComparison:
    """How the main checkout's default branch relates to its fetched origin."""

    relationship: str
    branch: str = ""
    behind_by: int = 0
    reason: str = ""

    @property
    def behind(self) -> bool:
        return self.behind_by > 0


def _git(repo_root: str, *args: str) -> Optional[str]:
    """Run one read-only git command, or ``None`` when it cannot answer."""
    try:
        completed = subprocess.run(
            ["git", "-C", repo_root, *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def head_commit(repo_root: str) -> Optional[str]:
    """The commit *repo_root* currently runs, or ``None`` when git cannot say.

    The identity of a checkout that carries no wheel version — what it is
    compared against a server build, and what names the engine a source install
    is about to serve its own universe with.
    """
    return _git(repo_root, "rev-parse", "HEAD")


def compare_to_server_build(repo_root: str, server_build: str) -> BuildComparison:
    """Relate this checkout's HEAD to the commit a server was built from.

    Never raises and never guesses. Every way of failing to answer returns
    ``UNKNOWN`` with the reason, because a wrong confident answer here is
    worse than an admitted absence: the caller's whole purpose is deciding
    whether a difference explains something else that just broke.

    Cached per ``(checkout, HEAD, server_build)`` for the process lifetime so
    a long-lived caller and a burst of short-lived helpers do not each walk
    git history again for the same pair.
    """
    head = head_commit(repo_root) or ""
    return _compare_to_server_build_cached(repo_root, server_build, head)


@lru_cache(maxsize=16)
def _compare_to_server_build_cached(
    repo_root: str, server_build: str, head: str
) -> BuildComparison:
    if not server_build:
        return BuildComparison(UNKNOWN, reason="server advertises no build")
    if not head:
        return BuildComparison(
            UNKNOWN,
            server_build=server_build,
            reason=f"{repo_root} is not a resolvable git checkout",
        )
    # A build the checkout has never fetched cannot be compared, and is a
    # different situation from being behind it.
    if _git(repo_root, "cat-file", "-e", f"{server_build}^{{commit}}") is None:
        return BuildComparison(
            UNKNOWN,
            local_head=head,
            server_build=server_build,
            reason="the server's build commit is not present in this checkout",
        )
    if head.startswith(server_build) or server_build.startswith(head):
        return BuildComparison(EQUAL, local_head=head, server_build=server_build)
    counts = _git(
        repo_root, "rev-list", "--left-right", "--count", f"{server_build}...HEAD"
    )
    if not counts:
        return BuildComparison(
            UNKNOWN,
            local_head=head,
            server_build=server_build,
            reason="could not count the distance between the two commits",
        )
    parts = counts.split()
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return BuildComparison(
            UNKNOWN,
            local_head=head,
            server_build=server_build,
            reason=f"unreadable commit distance {counts!r}",
        )
    behind, ahead = int(parts[0]), int(parts[1])
    if ahead and behind:
        relationship = DIVERGED
    elif ahead:
        relationship = AHEAD
    elif behind:
        relationship = BEHIND
    else:
        relationship = EQUAL
    return BuildComparison(
        relationship,
        local_head=head,
        server_build=server_build,
        ahead_by=ahead,
        behind_by=behind,
    )


def compare_main_to_origin(repo_root: str) -> OriginComparison:
    """Relate the main worktree's default branch to its last-fetched origin."""
    head = head_commit(repo_root) or ""
    return _compare_main_to_origin_cached(repo_root, head)


@lru_cache(maxsize=8)
def _compare_main_to_origin_cached(repo_root: str, head: str) -> OriginComparison:
    del head  # included in the cache key so a new commit recomputes
    listing = _git(repo_root, "worktree", "list", "--porcelain")
    first = (listing or "").splitlines()
    if not first or not first[0].startswith("worktree "):
        return OriginComparison(UNKNOWN, reason="main checkout is not resolvable")
    main_root = first[0].removeprefix("worktree ").strip()
    remote_head = _git(
        main_root,
        "symbolic-ref",
        "--quiet",
        "--short",
        "refs/remotes/origin/HEAD",
    )
    if not remote_head or not remote_head.startswith("origin/"):
        return OriginComparison(UNKNOWN, reason="origin default branch is unknown")
    branch = remote_head.removeprefix("origin/")
    counts = _git(
        main_root,
        "rev-list",
        "--left-right",
        "--count",
        f"refs/heads/{branch}...refs/remotes/origin/{branch}",
    )
    parts = (counts or "").split()
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return OriginComparison(
            UNKNOWN, branch=branch, reason="default branch distance is unreadable"
        )
    local_only, origin_only = map(int, parts)
    if local_only and origin_only:
        relationship = DIVERGED
    elif origin_only:
        relationship = BEHIND
    elif local_only:
        relationship = AHEAD
    else:
        relationship = EQUAL
    return OriginComparison(relationship, branch=branch, behind_by=origin_only)


def _short(ref: str) -> str:
    """Abbreviate a commit sha; leave a tag or branch name readable."""
    if len(ref) == 40 and all(c in "0123456789abcdef" for c in ref):
        return ref[:12]
    return ref


def describe(comparison: BuildComparison) -> str:
    """One operator-facing line naming the gap and what closes it."""
    server = _short(comparison.server_build)
    head = _short(comparison.local_head)
    if comparison.relationship == EQUAL:
        return f"this checkout matches the server's build {server}"
    if comparison.relationship == AHEAD:
        return (
            f"this checkout is {comparison.ahead_by} commit(s) ahead of the "
            f"server's build {server} — deploy to close the gap, or expect "
            "behavior the server does not have yet"
        )
    if comparison.relationship == BEHIND:
        return (
            f"this checkout is {comparison.behind_by} commit(s) behind the "
            f"server's build {server} — pull to close the gap"
        )
    if comparison.relationship == DIVERGED:
        return (
            f"this checkout ({head}) and the server's build {server} have "
            f"diverged: {comparison.ahead_by} ahead, "
            f"{comparison.behind_by} behind"
        )
    return (
        "cannot tell whether this checkout matches the server's build: "
        f"{comparison.reason}"
    )


def describe_origin(comparison: OriginComparison) -> str:
    """One operator-facing line for a stale fetched default branch."""
    return (
        f"checkout is {comparison.behind_by} commit(s) behind "
        f"origin/{comparison.branch} — run `git pull --ff-only`"
    )


__all__ = [
    "AHEAD",
    "BEHIND",
    "DIVERGED",
    "EQUAL",
    "UNKNOWN",
    "BuildComparison",
    "OriginComparison",
    "compare_main_to_origin",
    "compare_to_server_build",
    "describe",
    "describe_origin",
]
