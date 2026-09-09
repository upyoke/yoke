"""What the checkout can say about one standalone item branch.

The reads a standalone merge depends on, isolated from the boundary that
sequences them, because their answers change as the merge proceeds: the
branch ref disappears with the engine's cleanup and ``changed_files``
collapses to nothing the moment the branch lands. Callers that need those
facts after either point read them from the recorded receipt instead
(:mod:`yoke_core.domain.item_merge_receipts`).

Every read fails soft — a git error reads as "the checkout does not say so"
rather than raising — so the boundary decides what an absent answer means.
The one exception is :func:`unlanded_patches`, whose absent answer would read
as "nothing left to land"; it separates an unreadable comparison from an empty
one so no caller can converge on a landing the checkout never confirmed.
"""

from __future__ import annotations

import subprocess
from typing import Optional


def _git(repo_root: str, *args: str) -> subprocess.CompletedProcess:
    """Run one read or publish with the credential its target requires.

    ``ls-remote`` and ``push`` here are the standalone merge's only contact
    with the remote, and the push is what publishes a landed base branch. A
    refusal comes back as a failed result carrying its own recovery, so the
    soft-failure reading above stays true and :func:`publish` still surfaces
    the reason.
    """
    from yoke_cli.config import credentialed_git

    return credentialed_git.run(["-C", str(repo_root), *args])


def git_out(repo_root: str, *args: str) -> str:
    """Trimmed stdout for a git read; empty when the command fails."""
    result = _git(repo_root, *args)
    return result.stdout.strip() if result.returncode == 0 else ""


def branch_exists(repo_root: str, branch: str) -> bool:
    return (
        _git(repo_root, "rev-parse", "--verify", f"refs/heads/{branch}").returncode == 0
    )


def head_of(repo_root: str, branch: str) -> str:
    """The commit a local branch points at; empty when it cannot be read."""
    return git_out(repo_root, "rev-parse", f"refs/heads/{branch}")


def remote_head_of(repo_root: str, branch: str) -> str:
    """The commit origin advertises for ``branch``; empty when absent.

    The exact ref is asked for, so a branch whose name prefixes another
    cannot answer for it. An unreadable remote answers empty, because the
    caller's response is to publish — which names its own failure if the
    remote is genuinely unreachable.
    """
    listing = git_out(
        repo_root, "ls-remote", "--heads", "origin", f"refs/heads/{branch}"
    )
    return listing.split()[0] if listing else ""


def remote_branch_exists(repo_root: str, branch: str) -> bool:
    """Whether origin advertises ``branch``."""
    return bool(remote_head_of(repo_root, branch))


def is_ancestor(repo_root: str, commit: str, target: str) -> bool:
    """Whether ``target`` already contains ``commit``."""
    return (
        _git(repo_root, "merge-base", "--is-ancestor", commit, target).returncode == 0
    )


def fetch_target(repo_root: str, target: str) -> None:
    """Refresh ``origin/<target>`` before anything reads it.

    Best effort: a checkout with no remote, or one that cannot reach it,
    still answers from the refs it already holds.
    """
    _git(repo_root, "fetch", "origin", target)


def containing_ref(repo_root: str, commit: str, target: str) -> str:
    """Which ref already holds ``commit`` — ``target``, its remote, or empty.

    A queue-routed merge lands entirely on GitHub, so the local base branch
    legitimately does not contain the commit until it is fetched; refusing on
    the local answer alone strands a merge that already happened. Callers that
    go on to read the landing need to know which of the two answered, because
    a diff taken against the ref that does not contain it says nothing.
    """
    if not commit:
        return ""
    if is_ancestor(repo_root, commit, target):
        return target
    if not has_remote(repo_root):
        return ""
    fetch_target(repo_root, target)
    remote = f"origin/{target}"
    return remote if is_ancestor(repo_root, commit, remote) else ""


def is_landed(repo_root: str, commit: str, target: str) -> bool:
    """Whether ``commit`` has reached ``target`` locally or at the remote."""
    return bool(containing_ref(repo_root, commit, target))


def current_base_ref(repo_root: str, target: str) -> str:
    """The freshest ref for the base branch: ``origin/<target>``, else local.

    A close-out re-entered from a lane reads a local base branch that can be
    many merges behind, and every question about what has already landed is
    answered wrongly when asked of a stale base.
    """
    if not has_remote(repo_root):
        return target
    fetch_target(repo_root, target)
    remote = f"origin/{target}"
    return remote if git_out(repo_root, "rev-parse", "--verify", remote) else target


def unlanded_patches(
    repo_root: str, commit: str, base: str
) -> Optional[tuple[str, ...]]:
    """Commits reachable from ``commit`` whose patch ``base`` does not carry.

    ``git cherry`` compares patch identity rather than sha, which is the only
    read that recognises a lane rebased after its own landing: the base holds
    the work, the lane holds fresh shas for the same patches, and no ancestry
    read connects the two.

    ``None`` when the comparison could not run, so a caller cannot read an
    unreadable checkout as "nothing left to land".
    """
    if not commit or not base:
        return None
    result = _git(repo_root, "cherry", base, commit)
    if result.returncode != 0:
        return None
    return tuple(
        line.split(maxsplit=1)[-1]
        for line in result.stdout.splitlines()
        if line.startswith("+")
    )


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
    return False, (f"merge landed locally but publishing '{target}' failed: {detail}")


__all__ = [
    "branch_exists",
    "changed_files",
    "containing_ref",
    "current_base_ref",
    "fetch_target",
    "git_out",
    "head_of",
    "has_remote",
    "is_ancestor",
    "is_landed",
    "publish",
    "remote_branch_exists",
    "remote_head_of",
    "unlanded_patches",
]
