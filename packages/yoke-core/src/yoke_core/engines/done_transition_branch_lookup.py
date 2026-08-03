"""Find an item's branch when no worktree lane record survives.

The done transition normally merges the branch named by the item's active
lane. When no lane row remains, the branch name has to be derived — and a
branch is named for the item's public ref, which stops matching the
internal id once a project's sequence diverges from it. Probing a single
constructed name therefore misses the branch and the transition silently
continues without a merge.

:func:`branch_exists_for_item` probes every name the item could carry —
its current public ref, the legacy internal-id form, and any branch
recorded on a released lane — locally first, then on the remote.
"""

from __future__ import annotations

from typing import Any, Callable

from yoke_core.domain.worktree_naming import candidate_worktree_names


def branch_exists_for_item(
    item_id: int,
    *,
    project_repo: Any,
    run_git: Callable[..., Any],
    connect: Callable[[], Any],
) -> bool:
    """Return True when any name this item could carry names a branch."""
    with connect() as conn:
        candidates = candidate_worktree_names(conn, item_id)

    for candidate in sorted(candidates):
        verify = run_git(
            ["-C", str(project_repo), "rev-parse", "--verify", candidate],
            capture=True,
        )
        if verify.returncode == 0:
            return True
        listed = run_git(
            ["-C", str(project_repo), "ls-remote", "--heads", "origin", candidate],
            capture=True,
        )
        if listed.stdout and candidate in listed.stdout:
            return True
    return False


__all__ = ["branch_exists_for_item"]
