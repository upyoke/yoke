"""Bind a standalone lane name to its recorded merge source."""

from __future__ import annotations

from yoke_core.engines.merge_worktree_prepare import MergeContext


def bind_recorded_source(ctx: MergeContext, current_branch_sha: str) -> str:
    """Return an error or atomically point the lane ref at recorded HEAD."""
    source_sha = ctx.args.source_sha
    if not source_sha:
        return ""
    from yoke_core.engines import merge_worktree as mw

    source = mw._run_git(
        ["rev-parse", "--verify", f"{source_sha}^{{commit}}"],
        cwd=ctx.repo_root,
        capture=True,
    )
    if source.returncode != 0:
        return f"recorded lane HEAD {source_sha} is not a commit"
    rebound = mw._run_git(
        [
            "update-ref",
            f"refs/heads/{ctx.args.branch}",
            source_sha,
            current_branch_sha,
        ],
        cwd=ctx.repo_root,
        capture=True,
    )
    if rebound.returncode != 0:
        return (
            "lane branch changed while binding its recorded HEAD; "
            "retry after the competing update stops"
        )
    return ""


__all__ = ["bind_recorded_source"]
