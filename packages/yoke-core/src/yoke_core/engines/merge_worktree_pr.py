"""Pull-request merge workflow for merge-worktree."""

from __future__ import annotations

from yoke_core.engines.merge_worktree_prepare import MergeContext
from yoke_core.engines.merge_worktree_post_helpers import _post_merge_cleanup
from yoke_core.engines.merge_worktree_pr_rest import (
    create_pr,
    find_existing_pr,
)
from yoke_core.engines.merge_worktree_pr_merge import (
    run_pr_merge_with_retry_guard,
)
from yoke_core.engines.merge_worktree_pr_setup import (
    _current_origin_target_sha,
    _ensure_target_pushed,
)
from yoke_core.engines.merge_worktree_ci import (
    _classify_test_results,
    _read_item_test_results,
    _wait_for_ci,
)
from yoke_core.engines.merge_worktree_ci_rest import get_pr_head_sha
from yoke_core.domain.item_test_results_classify import evaluate_ci_substitute


def _parent():
    from yoke_core.engines import merge_worktree as _mw
    return _mw







def do_pr_merge(ctx: MergeContext) -> int:
    """Execute the push + PR + CI + merge workflow.

    Preconditions (enforced by ``run()``):
      - Local ``{target}`` has already been pushed to origin, and
        ``ctx.target_sha_at_validation`` holds the SHA that was pushed.
      - Trial merge + rebase/merge-commit already succeeded against the same
        post-push origin target.

    This function is fail-fast: every ``git push`` / REST PR-create /
    REST PR-checks / REST PR-merge step checks its result and emits a
    ``MergePullRequest*Failed`` event on failure before returning exit 1.

    Never falls through to PR-merge with empty identifiers — empty
    ``pr_url`` or empty ``pr_num`` are hard failures.
    """
    mw = _parent()
    _print = mw._print
    _run_git = mw._run_git
    _emit_merge_event = mw._emit_merge_event
    _fail_merge_subprocess = mw._fail_merge_subprocess  # still used for branch-push failure
    _fail_merge_rest = mw._fail_merge_rest

    # No-op detection: nothing to merge if branch has no unique commits.
    unique = _run_git(
        ["log", f"origin/{ctx.args.target}..{ctx.args.branch}", "--oneline"],
        cwd=ctx.repo_root, capture=True,
    )
    unique_count = (
        len(unique.stdout.strip().splitlines()) if unique.stdout.strip() else 0
    )

    if unique_count == 0:
        _print("No unique commits after rebase \u2014 nothing to merge. Cleaning up.")
        return _post_merge_cleanup(ctx, no_changes=True, pr_num="")

    # 1. Push branch -- fail-fast on push failure.
    _print(f"Pushing {ctx.args.branch}...")
    push_branch = _run_git(
        ["push", "-u", "origin", ctx.args.branch, "--force-with-lease"],
        cwd=ctx.worktree_path, capture=True,
    )
    if push_branch.returncode != 0:
        return _fail_merge_subprocess(
            "branch-push",
            push_branch,
            ctx=ctx,
            event_name="MergeBranchPushFailed",
            extra_detail=(
                "Branch force-with-lease push failed.  Inspect remote state "
                "and retry; worktree preserved."
            ),
        )
    _emit_merge_event(
        "MergeBranchPushed",
        outcome="success",
        item_id=ctx.item_id,
        context={
            "branch": ctx.args.branch,
            "target": ctx.args.target,
        },
    )

    # 2. Create PR via REST -- reuse an existing open PR if create says
    #    "already exists".  Never continue with empty pr_url /
    #    pr_num.
    _print("Creating pull request...")
    create_result = create_pr(
        ctx,
        title=f"Merge {ctx.args.branch}",
        body=f"Auto-generated PR for worktree branch {ctx.args.branch}.",
    )
    pr_url = create_result.pr_url
    pr_num = create_result.pr_num

    if create_result.already_exists or (not pr_url and not create_result.error_detail):
        _print(
            "REST pr-create reported no new PR (likely existing PR) \u2014 "
            "attempting to discover and reuse."
        )
        reused_url, reused_num = find_existing_pr(ctx)
        if reused_url and reused_num:
            pr_url = reused_url
            pr_num = reused_num
            _print(f"Reusing existing PR: {pr_url}")
        else:
            return _fail_merge_rest(
                "pr-create-existing-unresolvable",
                ctx=ctx,
                event_name="MergePullRequestCreateFailed",
                error_detail=create_result.error_detail
                or "existing-PR signal returned but discovery turned up no open PR",
                extra_detail=(
                    "REST pr-create indicated an existing PR but no open PR "
                    f"could be discovered for head '{ctx.args.branch}'.  "
                    "Resolve the state manually (close the stale PR or "
                    "rebase the branch) and retry."
                ),
            )
    elif create_result.error_detail:
        return _fail_merge_rest(
            "pr-create",
            ctx=ctx,
            event_name="MergePullRequestCreateFailed",
            error_detail=create_result.error_detail,
            extra_detail=(
                "REST pr-create failed before returning a usable PR URL. "
                "No merge attempt was made; the branch remains pushed."
            ),
        )
    else:
        _emit_merge_event(
            "MergePullRequestCreated",
            outcome="success",
            item_id=ctx.item_id,
            context={
                "branch": ctx.args.branch,
                "target": ctx.args.target,
                "pr_url": pr_url,
                "pr_num": pr_num,
            },
        )

    if not pr_url or not pr_num:
        return _fail_merge_rest(
            "pr-identifier-validation",
            ctx=ctx,
            event_name="MergePullRequestCreateFailed",
            error_detail=f"empty PR identifiers (url={pr_url!r} num={pr_num!r})",
            extra_detail="Refusing to merge with an empty PR identifier.",
        )

    _print(f"PR: {pr_url}")

    # 3. Wait for CI.
    ci_result = _wait_for_ci(pr_num, ctx)
    if ci_result.outcome == "failed":
        _emit_merge_event(
            "MergePullRequestCiFailed",
            severity="ERROR",
            outcome="failure",
            item_id=ctx.item_id,
            context={
                "branch": ctx.args.branch,
                "target": ctx.args.target,
                "pr_num": pr_num,
            },
        )
        return 1
    if ci_result.outcome == "skipped":
        # No required CI was configured. The merge gate's "no checks → pass"
        # path was a silent false positive; substitute items.test_results
        # local-verification evidence when polish captured a PASS verdict,
        # or refuse the merge when no evidence exists.
        _emit_merge_event(
            "MergePullRequestCiSkipped",
            outcome="success",
            item_id=ctx.item_id,
            context={
                "branch": ctx.args.branch,
                "target": ctx.args.target,
                "pr_num": pr_num,
                "reason": ci_result.reason or "no_checks_configured",
            },
        )
        raw_results = _read_item_test_results(ctx.item_id or "")
        verdict = _classify_test_results(raw_results)
        # A PASS only substitutes for CI when provably bound to
        # the PR head SHA; a stale (pre-rebase / pre-fix) or unstamped verdict
        # is refused. The decision lives in the domain classifier; the engine
        # owns event emission. The head SHA is read only on the PASS path.
        head_sha, head_sha_err = (
            get_pr_head_sha(ctx, pr_num) if verdict == "passed" else ("", None)
        )
        accept, evidence_state, reason_phrase = evaluate_ci_substitute(
            verdict, raw_results, head_sha, head_sha_err
        )
        if accept:
            # Name the local-only gating loudly — this merge carries no
            # required CI signal, only a fresh local verdict bound to head.
            _emit_merge_event(
                "LocalVerificationAcceptedAsCiSubstitute",
                severity="WARN",
                outcome="success",
                item_id=ctx.item_id,
                context={
                    "branch": ctx.args.branch,
                    "target": ctx.args.target,
                    "pr_num": pr_num,
                    "evidence_source": "items.test_results",
                    "verdict_head_sha": head_sha,
                    "ci_skip_reason": ci_result.reason or "no_checks_configured",
                },
            )
            _print(
                "WARNING: merging on a fresh local test verdict only — no "
                f"required CI checks gated PR {pr_num} "
                f"(reason: {ci_result.reason or 'no_checks_configured'}).",
                err=True,
            )
        else:
            # Refuse an empty, failed, stale, or unbound verdict.
            _emit_merge_event(
                "MergeBlockedNoVerificationEvidence",
                severity="ERROR",
                outcome="failure",
                item_id=ctx.item_id,
                context={
                    "branch": ctx.args.branch,
                    "target": ctx.args.target,
                    "pr_num": pr_num,
                    "evidence_source": "items.test_results",
                    "evidence_state": evidence_state,
                    "verdict_head_sha": head_sha,
                },
            )
            _print(
                "Merge refused: no required CI checks gated this PR and "
                "items.test_results is " + reason_phrase
                + ". Run `/yoke polish` to capture a fresh passing pytest "
                "verdict bound to the current head, or configure required CI "
                "checks on the target repo.",
                err=True,
            )
            return 1
    else:
        _emit_merge_event(
            "MergePullRequestCiPassed",
            outcome="success",
            item_id=ctx.item_id,
            context={
                "branch": ctx.args.branch,
                "target": ctx.args.target,
                "pr_num": pr_num,
            },
        )

    # 4. Freshness re-check (second half): make sure nobody pushed to
    #    origin/{target} between validation and the REST merge call.  If
    #    the target moved, abort loudly and preserve the worktree so the
    #    operator can retry cleanly.
    current_sha = _current_origin_target_sha(ctx)
    expected_sha = ctx.target_sha_at_validation
    if expected_sha and current_sha and current_sha != expected_sha:
        _print("", err=True)
        _print(
            f"Error: origin/{ctx.args.target} moved during the merge window. "
            f"Expected {expected_sha[:12]}, got {current_sha[:12]}.",
            err=True,
        )
        _print(
            "Aborting before REST merge to avoid merging stale validation. "
            "Re-run `/yoke usher` to retry; worktree preserved.",
            err=True,
        )
        _emit_merge_event(
            "MergeTargetStale",
            severity="ERROR",
            outcome="failure",
            item_id=ctx.item_id,
            context={
                "branch": ctx.args.branch,
                "target": ctx.args.target,
                "expected_sha": expected_sha,
                "current_sha": current_sha,
                "pr_num": pr_num,
            },
        )
        return 1

    # 5. Merge the PR -- final subprocess that must be checked.
    _print(f"Merging PR #{pr_num}...")
    _emit_merge_event(
        "MergePullRequestMergeStarted",
        outcome="attempt",
        item_id=ctx.item_id,
        context={
            "branch": ctx.args.branch,
            "target": ctx.args.target,
            "pr_num": pr_num,
            "pr_url": pr_url,
        },
    )
    merge_outcome = run_pr_merge_with_retry_guard(pr_num, pr_url, ctx, _emit_merge_event)
    if not merge_outcome.success:
        return _fail_merge_rest(
            "pr-merge",
            ctx=ctx,
            event_name="MergePullRequestMergeFailed",
            error_detail=merge_outcome.error_detail or "REST merge call failed",
            extra_detail=(
                f"REST merge for PR #{pr_num} failed.  Worktree preserved.  "
                "Resolve the PR state on GitHub (conflicts, required reviews, "
                "mergeability) and re-run `/yoke usher`."
            ),
        )

    # Success print moves into _post_merge_cleanup so it only appears after
    # ancestry verification.
    return _post_merge_cleanup(ctx, no_changes=False, pr_num=pr_num)
