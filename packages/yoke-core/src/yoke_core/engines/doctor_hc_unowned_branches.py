"""Local branches no lane owns whose changes the default branch already holds.

Agents sometimes park work on side branches — a ``*-presquash`` backup, a
``*-pre-settings`` copy — that no item records, so no lane sweep ever reaches
them. ``HC-worktree-health`` names each such branch once its changes are
already on the default branch (``lane_adds_nothing``), so an operator can
delete it. This module only reports: a branch no item owns is never deleted
automatically.
"""

from __future__ import annotations

from typing import Iterable, List

from yoke_core.domain.standalone_item_merge_git import git_out, lane_adds_nothing
from yoke_core.engines.doctor_parallel_reads import bounded_read_map


def default_branch(repo_root: str) -> str:
    """The branch ``origin/HEAD`` names, else a local ``main``; ``""`` if neither."""
    remote_head = git_out(
        repo_root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD"
    )
    if remote_head.startswith("origin/"):
        return remote_head.removeprefix("origin/")
    return (
        "main" if git_out(repo_root, "rev-parse", "--verify", "refs/heads/main") else ""
    )


def unowned_landed_branches(
    repo_root: str,
    *,
    local_branches: Iterable[str],
    owned_branches: Iterable[str],
    checked_out: Iterable[str],
    default_branch: str,
) -> List[str]:
    """Branches with no lane row, not the default, not checked out, and landed."""
    owned = set(owned_branches) | set(checked_out) | {default_branch}
    candidates = sorted(branch for branch in set(local_branches) if branch not in owned)
    if not candidates or not default_branch:
        return []
    verdicts = bounded_read_map(
        lambda branch: lane_adds_nothing(repo_root, branch, default_branch),
        candidates,
    )
    return [
        branch for branch, adds_nothing in zip(candidates, verdicts) if adds_nothing
    ]


def unowned_branch_issues(
    repo_root: str,
    *,
    local_branches: Iterable[str],
    owned_branches: Iterable[str],
    checked_out: Iterable[str],
    default_branch: str,
) -> List[str]:
    """One report line per landed branch no item owns."""
    return [
        f"- Unowned local branch: {branch} — no item records it and "
        f"{default_branch} already holds its changes; delete it with "
        f"`git branch -D {branch}` once you have confirmed nothing else needs it"
        for branch in unowned_landed_branches(
            repo_root,
            local_branches=local_branches,
            owned_branches=owned_branches,
            checked_out=checked_out,
            default_branch=default_branch,
        )
    ]


__all__ = ["default_branch", "unowned_branch_issues", "unowned_landed_branches"]
