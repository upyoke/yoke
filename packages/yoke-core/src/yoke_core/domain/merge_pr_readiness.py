"""Draft readiness at the standalone landing and read-only check boundaries."""

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain.merge_context import MergeArgs, MergeContext
from yoke_core.domain.merge_github_discovery import find_existing_pr
from yoke_core.domain.merge_github_queue import mark_ready_for_review, read_pr_landing_state


def prepare_pull_request(ctx: MergeContext, pr_num: str, *, emit) -> str:
    state, error = read_pr_landing_state(ctx, pr_num)
    if error or state is None:
        return compose_refusal(
            f"pr_ready_for_review_failed: {error or 'pull request unreadable'}",
            recovery=f"read PR {pr_num} on GitHub and re-run `yoke merge item`"
        )
    if state.draft:
        result = mark_ready_for_review(ctx, pr_num)
        if not result.success:
            return result.error_detail
        emit(f"marked PR {pr_num} ready for review")
    return ""


def check_standalone_draft(readiness, *, item) -> None:
    ctx = MergeContext(
        args=MergeArgs(branch=readiness.branch, target=readiness.target),
        repo_root=str(readiness.repo_root),
        project=str((item.get("project") or {}).get("slug") or ""),
    )
    _url, pr_num = find_existing_pr(ctx)
    if pr_num:
        state, error = read_pr_landing_state(ctx, pr_num)
        if error:
            readiness.merge_will.append(f"recheck pull request {pr_num}: {error}")
        elif state is not None and state.draft:
            readiness.merge_will.append(f"mark PR {pr_num} ready for review")
