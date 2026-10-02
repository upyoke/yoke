"""Select the existing default-branch ref for local merge preparation."""

from __future__ import annotations

from yoke_core.engines.merge_worktree_context import MergeContext


def target_ref(ctx: MergeContext) -> str:
    """Use the remote-tracking target when present, otherwise the local branch."""
    from yoke_core.engines import merge_worktree

    remote = f"origin/{ctx.args.target}"
    exists = merge_worktree._run_git(
        ["rev-parse", "--verify", f"refs/remotes/{remote}"],
        cwd=ctx.worktree_path,
        capture=True,
    )
    return remote if exists.returncode == 0 else ctx.args.target
