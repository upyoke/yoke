"""PR setup helpers for merge-worktree."""

from __future__ import annotations

from typing import Optional, Tuple

from yoke_core.engines.merge_worktree_prepare import MergeContext
from yoke_core.engines.merge_worktree_pr_rest import find_existing_pr


def _parent():
    from yoke_core.engines import merge_worktree as _mw
    return _mw

def _current_origin_target_sha(ctx: MergeContext) -> Optional[str]:
    """Fetch origin and return the current origin/{target} SHA, or None."""
    mw = _parent()
    _run_git = mw._run_git

    _run_git(["fetch", "origin", ctx.args.target], cwd=ctx.repo_root, capture=True)
    result = _run_git(
        ["rev-parse", f"origin/{ctx.args.target}"], cwd=ctx.repo_root, capture=True
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None


def _ensure_target_pushed(ctx: MergeContext) -> Optional[int]:
    """Push local {target} to origin if ahead, capture post-push SHA.

    Runs BEFORE trial merge so trial validation happens against the same
    origin state GitHub will eventually merge into.

    Returns:
        None on success (``ctx.target_sha_at_validation`` populated).
        An exit code (int) on failure.
    """
    mw = _parent()
    _print = mw._print
    _run_git = mw._run_git
    _emit_merge_event = mw._emit_merge_event
    _fail_merge_subprocess = mw._fail_merge_subprocess

    _run_git(["fetch", "origin", ctx.args.target], cwd=ctx.repo_root, capture=True)

    ahead = _run_git(
        ["rev-list", f"origin/{ctx.args.target}..{ctx.args.target}", "--count"],
        cwd=ctx.repo_root, capture=True,
    )
    ahead_count = (
        int(ahead.stdout.strip()) if ahead.returncode == 0 and ahead.stdout.strip() else 0
    )

    if ahead_count > 0:
        _print(
            f"Local {ctx.args.target} is {ahead_count} commit(s) ahead of origin \u2014 "
            "pushing before validation..."
        )
        push_result = _run_git(
            ["push", "origin", ctx.args.target], cwd=ctx.repo_root, capture=True
        )
        if push_result.returncode != 0:
            return _fail_merge_subprocess(
                "push-local-target",
                push_result,
                ctx=ctx,
                event_name="MergeTargetPushFailed",
                extra_detail=(
                    "Cannot push local {target} to origin. "
                    "Resolve the remote divergence (e.g. `git -C {repo} pull --rebase origin {target}`) "
                    "and retry the merge."
                ).format(repo=ctx.repo_root, target=ctx.args.target),
            )
        _print(f"Pushed local {ctx.args.target} \u2014 origin is now up to date.")

    sha = _current_origin_target_sha(ctx)
    if not sha:
        _print(
            f"Error: unable to read origin/{ctx.args.target} SHA after push.",
            err=True,
        )
        _emit_merge_event(
            "MergeTargetPushFailed",
            severity="ERROR",
            outcome="failure",
            item_id=ctx.item_id,
            context={
                "phase": "capture-target-sha",
                "branch": ctx.args.branch,
                "target": ctx.args.target,
                "reason": "origin rev-parse returned empty",
            },
        )
        return 1

    ctx.target_sha_at_validation = sha
    _emit_merge_event(
        "MergeTargetValidated",
        outcome="success",
        item_id=ctx.item_id,
        context={
            "branch": ctx.args.branch,
            "target": ctx.args.target,
            "target_sha": sha,
            "local_pushed_ahead": ahead_count,
        },
    )
    return None


def _discover_existing_pr(ctx: MergeContext) -> Tuple[Optional[str], Optional[str]]:
    """Look up an existing open PR for the branch via REST.

    Returns (pr_url, pr_num) on success, or (None, None) when no open PR
    matches or discovery itself fails. Emits MergePullRequestReused on reuse.
    """
    _emit_merge_event = _parent()._emit_merge_event

    url, num_str = find_existing_pr(ctx)
    if not url or not num_str:
        return None, None

    _emit_merge_event(
        "MergePullRequestReused",
        outcome="success",
        item_id=ctx.item_id,
        context={
            "branch": ctx.args.branch,
            "target": ctx.args.target,
            "pr_url": url,
            "pr_num": num_str,
        },
    )
    return url, num_str
