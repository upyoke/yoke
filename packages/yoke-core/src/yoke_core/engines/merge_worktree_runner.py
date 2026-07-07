"""Top-level merge-worktree orchestration."""

from __future__ import annotations

import time
from typing import Callable, Optional

from yoke_core.engines.merge_worktree_prepare import MergeArgs
from yoke_core.engines.merge_worktree_pr_rest import validate_pat_for_merge


# Exit code returned when the pre-acquire merge-lock retry budget is exhausted
# and the block message is still present. Distinct from existing engine exit
# codes 1/3/4/5 so .agents/skills/yoke/usher/merge.md can treat it as a
# retryable coordination outcome instead of a halt-class merge failure.
RECOVERABLE_MERGE_LOCK_EXIT_CODE = 6

# Pre-acquire merge-lock retry schedule (seconds). The first attempt runs
# immediately; each entry is the sleep BEFORE the next retry. The total wall
# wait when the block never clears is the sum (~9s). Tests monkeypatch
# ``time.sleep`` so the suite incurs no real delay.
MERGE_LOCK_RETRY_DELAYS = (1.0, 3.0, 5.0)


def _pre_acquire_check_with_retry(
    check_fn: Callable[[], Optional[str]],
    *,
    sleep_fn: Optional[Callable[[float], None]] = None,
    delays: tuple[float, ...] = MERGE_LOCK_RETRY_DELAYS,
) -> Optional[str]:
    """Call ``check_fn`` with bounded retries; return final block message or None.

    Calls ``check_fn`` once immediately. If it returns a non-None block message,
    sleep for each entry in ``delays`` and retry. As soon as ``check_fn`` returns
    None (stale row pruned by a subsequent check, or holder released), return
    None so the caller proceeds to acquire. If every retry still reports a
    block, return the most recent block message. ``sleep_fn`` defaults to
    ``time.sleep`` via module-attribute lookup so tests can monkeypatch the
    ``time`` module without binding a stale default.
    """
    if sleep_fn is None:
        sleep_fn = time.sleep
    block_msg = check_fn()
    if block_msg is None:
        return None
    for delay in delays:
        sleep_fn(delay)
        block_msg = check_fn()
        if block_msg is None:
            return None
    return block_msg


def _parent():
    from yoke_core.engines import merge_worktree as _mw
    return _mw

def run(args: MergeArgs) -> int:
    """Execute the full merge workflow. Returns exit code."""
    # Import here to avoid circular imports at module level
    from yoke_core.domain import merge_lock

    mw = _parent()
    validate_args = mw.validate_args
    _print = mw._print
    resolve_context = mw.resolve_context
    _run_git = mw._run_git
    _already_merged_message = mw._already_merged_message
    _emit_merge_event = mw._emit_merge_event
    preflight_checks = mw.preflight_checks
    check_and_clean_root_dirty_state = mw.check_and_clean_root_dirty_state
    prune_agent_worktrees = mw.prune_agent_worktrees
    extract_generated_files = mw.extract_generated_files
    _pre_merge_integration = mw._pre_merge_integration
    _ensure_target_pushed = mw._ensure_target_pushed
    _stash_classify_gate = mw._stash_classify_gate
    trial_merge = mw.trial_merge
    do_rebase_or_merge = mw.do_rebase_or_merge
    run_tests = mw.run_tests
    do_local_merge = mw.do_local_merge
    do_pr_merge = mw.do_pr_merge

    # Validate
    err = validate_args(args)
    if err:
        _print(err, err=True)
        return 1

    # Resolve context first so the PAT precondition has the project on hand.
    try:
        ctx = resolve_context(args)
    except RuntimeError as e:
        _print(str(e), err=True)
        return 1

    # Require a readable GitHub PAT for non-local merges. Local merges
    # never touch GitHub and remain exempt from the auth precondition.
    if not args.local_merge:
        ok, message = validate_pat_for_merge(ctx)
        if not ok:
            _print(message or "Error: GitHub PAT validation failed.", err=True)
            return 1

    # Verify branch exists
    verify = _run_git(
        ["rev-parse", "--verify", f"refs/heads/{args.branch}"], cwd=ctx.repo_root, capture=True
    )
    if verify.returncode != 0:
        _print(f"Error: branch '{args.branch}' does not exist as a local ref.", err=True)
        return 1

    # Already-merged guard
    already = _run_git(
        ["merge-base", "--is-ancestor", args.branch, args.target],
        cwd=ctx.repo_root, capture=True,
    )
    if already.returncode == 0:
        _print(_already_merged_message(args.branch, args.target, ctx.repo_root))
        _print(f"YOKE_REPO_ROOT={ctx.yoke_repo_root}")
        return 0

    # Also check origin
    _run_git(["fetch", "origin", args.target], cwd=ctx.repo_root, capture=True)
    already_origin = _run_git(
        ["merge-base", "--is-ancestor", args.branch, f"origin/{args.target}"],
        cwd=ctx.repo_root, capture=True,
    )
    if already_origin.returncode == 0:
        _print(_already_merged_message(args.branch, args.target, ctx.repo_root))
        _print(f"YOKE_REPO_ROOT={ctx.yoke_repo_root}")
        return 0

    # Branch mismatch correction
    if ctx.worktree_path != ctx.repo_root:
        actual = _run_git(
            ["branch", "--show-current"], cwd=ctx.worktree_path, capture=True
        )
        if actual.returncode == 0 and actual.stdout.strip():
            actual_branch = actual.stdout.strip()
            if actual_branch != args.branch:
                _print(f"Warning: branch mismatch detected. Correcting to {actual_branch}.", err=True)
                args.branch = actual_branch

    # DB merge lock
    lock_handle = None
    try:
        if args.force_lock:
            merge_lock.force_clear()
        # Bounded retry: orphan-PID rows often get pruned by a subsequent
        # ``check()`` call seconds later. Retry around the pre-acquire check
        # so transient stale-lock conditions don't surface as halt-class merge
        # failures.
        block_msg = _pre_acquire_check_with_retry(merge_lock.check)
        if block_msg:
            _print(block_msg, err=True)
            _print(
                "Recovery: retryable merge-lock condition "
                "(pre-acquire retry budget exhausted). Rerun "
                f"merge for branch '{args.branch}' once the holding lock clears.",
                err=True,
            )
            return RECOVERABLE_MERGE_LOCK_EXIT_CODE
        lock_handle = merge_lock.acquire(args.branch, ctx.epic_id)
    except Exception as e:
        _print(f"Merge lock error: {e}", err=True)
        return 1

    _emit_merge_event(
        "MergeEngineStarted",
        outcome="attempt",
        item_id=ctx.item_id,
        context={
            "branch": args.branch,
            "target": args.target,
            "epic_id": ctx.epic_id,
            "local_merge": args.local_merge,
        },
    )

    exit_code: int = 1
    try:
        # Preflight
        pf_result = preflight_checks(ctx)
        if pf_result:
            exit_code = pf_result[0]
            return exit_code

        # Dirty state
        dirty_result = check_and_clean_root_dirty_state(ctx)
        if dirty_result:
            exit_code = dirty_result[0]
            return exit_code

        # Prune agent worktrees
        prune_agent_worktrees(ctx.repo_root)

        # Extract generated files
        ctx.generated_files = extract_generated_files(ctx)

        # Fetch target
        _run_git(["fetch", "origin", args.target], cwd=ctx.worktree_path, capture=True)

        # Pre-merge main integration
        _pre_merge_integration(ctx)

        # Push local {target} to origin BEFORE trial merge so trial validation
        # runs against the same origin state GitHub will merge into later
        # .  This also populates ``ctx.target_sha_at_validation``
        # which do_pr_merge re-checks right before the REST merge call.
        if not args.local_merge:
            push_target_exit = _ensure_target_pushed(ctx)
            if push_target_exit is not None:
                exit_code = push_target_exit
                return exit_code

        # Stash-classify-gate
        stash_result = _stash_classify_gate(ctx)
        if stash_result:
            exit_code = stash_result[0]
            return exit_code

        # Compute branch-changed files (for doc conflict resolution)
        mb = _run_git(
            ["merge-base", "HEAD", f"origin/{args.target}"], cwd=ctx.worktree_path, capture=True
        )
        if mb.returncode == 0 and mb.stdout.strip():
            diff = _run_git(
                ["diff", "--name-only", mb.stdout.strip(), "HEAD"],
                cwd=ctx.worktree_path, capture=True,
            )
            ctx.branch_changed_files = diff.stdout.strip().splitlines() if diff.stdout.strip() else []

        _print(f"Merging branch: {args.branch} \u2192 {args.target}")
        _print(f"Worktree: {ctx.worktree_path}")

        # Trial merge
        trial_result = trial_merge(ctx)
        if trial_result:
            exit_code = trial_result[0]
            return exit_code

        # Real rebase/merge
        merge_result = do_rebase_or_merge(ctx)
        if merge_result:
            exit_code = merge_result[0]
            return exit_code

        # Tests
        test_result = run_tests(ctx)
        if test_result:
            exit_code = test_result[0]
            return exit_code

        # Local or PR path
        if args.local_merge:
            exit_code = do_local_merge(ctx)
        else:
            exit_code = do_pr_merge(ctx)
        return exit_code

    finally:
        # Always release merge lock
        if lock_handle:
            try:
                merge_lock.release(lock_handle)
            except Exception:
                pass

        # Final engine-level telemetry -- success or failure.
        if exit_code == 0:
            _emit_merge_event(
                "MergeEngineSucceeded",
                outcome="success",
                item_id=ctx.item_id,
                context={
                    "branch": args.branch,
                    "target": args.target,
                    "epic_id": ctx.epic_id,
                },
            )
        elif exit_code == 5:
            # the precise MergeEngineFailed event with
            # ``phase=post_merge_cleanup`` / ``merge_committed=true`` has
            # already been emitted by ``_regenerate_views_or_exit5``.
            # Suppress the generic emission here so the events ledger
            # only carries the truthful post-merge-cleanup record.
            pass
        else:
            _emit_merge_event(
                "MergeEngineFailed",
                severity="ERROR",
                outcome="failure",
                item_id=ctx.item_id,
                context={
                    "branch": args.branch,
                    "target": args.target,
                    "epic_id": ctx.epic_id,
                    "exit_code": exit_code,
                },
            )
