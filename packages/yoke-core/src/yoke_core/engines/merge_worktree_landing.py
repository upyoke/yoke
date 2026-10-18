"""Record integration-lane landings before their retry checkout is retired."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_core.domain.item_landings_close_out import close_out_lane
from yoke_core.domain.item_merge_receipts import landing_merge_commit
from yoke_core.engines.merge_worktree_context import MergeContext


def record_worktree_landing(
    ctx: MergeContext, *, candidate_sha: str, target_sha: str, pr_num: str = ""
) -> bool:
    """Reuse item close-out's recorder; standalone close-out owns its own write."""
    if ctx.args.standalone or not ctx.epic_id:
        return True
    from yoke_core.engines import merge_worktree as mw

    try:
        merge_sha = landing_merge_commit(ctx.repo_root, target_sha, candidate_sha)
        _, note = close_out_lane(
            item_id=ctx.epic_id,
            branch=ctx.args.branch,
            target=ctx.args.target,
            repo_root=ctx.repo_root,
            outcome=SimpleNamespace(
                commit_sha=candidate_sha,
                merge_sha=merge_sha or candidate_sha,
                touched_files=ctx.branch_changed_files,
                pr_num=pr_num,
            ),
        )
    except Exception as exc:
        note = str(exc)
    if note:
        mw._print(
            f"item_landing_record_failed: landing is proven but bookkeeping "
            f"failed: {note}. Preserve the lane and retry the same merge-worktree "
            "command to record the landing and release its claims.",
            err=True,
        )
        return False
    return True


def record_existing_landing(ctx: MergeContext, candidate_sha: str, target: str) -> int:
    """Converge a previous successful merge whose bookkeeping was interrupted."""
    if ctx.args.standalone or not ctx.epic_id:
        return 0
    from yoke_core.engines import merge_worktree as mw

    tip = mw._run_git(["rev-parse", target], cwd=ctx.repo_root, capture=True)
    if tip.returncode:
        mw._print(
            "item_landing_target_unreadable: cannot resolve the proven target; "
            "restore the target ref and retry merge-worktree. Preserve the lane.",
            err=True,
        )
        return 5
    return (
        0
        if record_worktree_landing(
            ctx, candidate_sha=candidate_sha, target_sha=tip.stdout.strip()
        )
        else 5
    )
