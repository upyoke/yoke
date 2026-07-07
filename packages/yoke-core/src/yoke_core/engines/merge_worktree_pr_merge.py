"""PR-merge retry guard.

Wraps the REST :func:`merge_pr` helper with the merge-state-aware retry
the legacy subprocess wrapper provided. Lives in its own module so the
PR-create / discover / merge-state surface in
:mod:`merge_worktree_pr_rest` stays focused.
"""

from __future__ import annotations

from yoke_core.engines.merge_worktree_pr_rest import (
    PrMergeResult,
    get_pr_merge_state,
    merge_pr,
)
from yoke_core.engines.merge_worktree_prepare import MergeContext


def run_pr_merge_with_retry_guard(
    pr_num: str,
    pr_url: str,
    ctx: MergeContext,
    emit_merge_event,
) -> PrMergeResult:
    """Merge ``pr_num`` via REST with the merge-state-aware retry guard.

    The transport already retries on canonical transient signatures. This
    wrapper adds the pre-retry validation the legacy subprocess path
    provided: when the first attempt fails with a ``Base branch was
    modified`` envelope, re-check merge-state and only retry if it's
    clean / mergeable. Emits ``MergePullRequestMergeRetried`` on retry
    so operator analytics carry the same shape.
    """
    first = merge_pr(ctx, pr_num)
    if first.success:
        return first
    if first.retryable_signature != "graphql-base-branch-modified":
        return first

    state, state_err = get_pr_merge_state(ctx, pr_num)
    if state_err is not None or state is None:
        return PrMergeResult(
            success=False,
            error_detail=(
                (first.error_detail or "")
                + (
                    f"; merge-state recheck failed: {state_err}"
                    if state_err else ""
                )
            ),
        )
    if (
        state.merge_state_status.lower() != "clean"
        or state.mergeable.lower() != "true"
    ):
        return PrMergeResult(
            success=False,
            error_detail=(
                (first.error_detail or "")
                + f"; refusing retry, mergeable_state={state.merge_state_status!r} "
                f"mergeable={state.mergeable!r}"
            ),
        )

    emit_merge_event(
        "MergePullRequestMergeRetried",
        outcome="retry",
        item_id=ctx.item_id,
        context={
            "branch": ctx.args.branch,
            "target": ctx.args.target,
            "pr_num": pr_num,
            "pr_url": pr_url,
            "attempt_index": 1,
            "stderr_signature": first.retryable_signature,
            "merge_state_status": state.merge_state_status,
            "mergeable": state.mergeable,
        },
    )
    return merge_pr(ctx, pr_num)
