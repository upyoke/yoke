"""Top-level merge-worktree orchestration."""

from __future__ import annotations


from yoke_contracts.refusal_recovery import compose_refusal

from yoke_core.domain.merge_github_authority import (
    classify_merge_authority,
    merge_reaches_github,
)
from yoke_core.domain.standalone_item_merge_git import has_remote
from yoke_core.engines.merge_worktree_base import target_ref
from yoke_core.domain.merge_github_rest import validate_github_auth_for_merge
from yoke_core.domain.merge_context import MergeArgs

# Exit 6 means the full merge-lock TTL wait timed out, with its holder named.
RECOVERABLE_MERGE_LOCK_EXIT_CODE = 6


def _parent():
    from yoke_core.engines import merge_worktree as _mw

    return _mw


def run(args: MergeArgs) -> int:
    """Execute the full merge workflow. Returns exit code."""
    from yoke_core.domain import merge_lock, runtime_settings

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

    err = validate_args(args)
    if err:
        _print(err, err=True)
        return 1

    try:
        ctx = resolve_context(args)
    except RuntimeError as e:
        _print(str(e), err=True)
        return 1

    authority = classify_merge_authority(local_merge=args.local_merge)
    try:
        reaches_github = merge_reaches_github(
            local_merge=args.local_merge,
            standalone=args.standalone,
            repo_root=str(ctx.repo_root),
            project=ctx.project or "",
        )
    except RuntimeError as exc:
        _print(
            f"github_merge_mode_unreadable: {exc}. Retry the project GitHub binding status read before merging.",
            err=True,
        )
        return 1
    if reaches_github:
        ok, message = validate_github_auth_for_merge(ctx, authority)
        if not ok:
            _print(message or "Error: GitHub auth validation failed.", err=True)
            return 1

    verify = _run_git(
        ["rev-parse", "--verify", f"refs/heads/{args.branch}"],
        cwd=ctx.repo_root,
        capture=True,
    )
    if verify.returncode != 0:
        _print(
            f"Error: branch '{args.branch}' does not exist as a local ref.", err=True
        )
        return 1

    source_ref = args.source_sha or args.branch

    from yoke_core.engines.merge_worktree_landing import record_existing_landing

    already = _run_git(
        ["merge-base", "--is-ancestor", source_ref, args.target],
        cwd=ctx.repo_root,
        capture=True,
    )
    if already.returncode == 0:
        _print(_already_merged_message(args.branch, args.target, ctx.repo_root))
        _print(f"YOKE_REPO_ROOT={ctx.yoke_repo_root}")
        return record_existing_landing(ctx, verify.stdout.strip(), args.target)

    if has_remote(ctx.repo_root):
        _run_git(["fetch", "origin", args.target], cwd=ctx.repo_root, capture=True)
    already_origin = _run_git(
        ["merge-base", "--is-ancestor", source_ref, f"origin/{args.target}"],
        cwd=ctx.repo_root,
        capture=True,
    )
    if already_origin.returncode == 0:
        _print(_already_merged_message(args.branch, args.target, ctx.repo_root))
        _print(f"YOKE_REPO_ROOT={ctx.yoke_repo_root}")
        return record_existing_landing(
            ctx, verify.stdout.strip(), f"origin/{args.target}"
        )

    from yoke_core.engines.merge_worktree_recorded_source import (
        bind_recorded_source,
    )

    if source_error := bind_recorded_source(ctx, verify.stdout.strip()):
        _print(f"Error: {source_error}.", err=True)
        return 1

    if ctx.worktree_path != ctx.repo_root:
        actual = _run_git(
            ["branch", "--show-current"], cwd=ctx.worktree_path, capture=True
        )
        if actual.returncode == 0 and actual.stdout.strip():
            actual_branch = actual.stdout.strip()
            if actual_branch != args.branch:
                _print(
                    f"Warning: branch mismatch detected. Correcting to {actual_branch}.",
                    err=True,
                )
                args.branch = actual_branch

    lock_handle = None
    try:
        if args.force_lock:
            merge_lock.force_clear()
        scope = merge_lock.LockScope(
            project_slug=ctx.project or "",
            target_branch=args.target,
        )
        from yoke_core.engines import merge_lock_wait

        acquired = merge_lock_wait.wait_and_acquire(
            scope, args.branch, ctx.epic_id, print_fn=_print
        )
        if isinstance(acquired, str):
            ttl = runtime_settings.get_int(
                "merge_lock_ttl_minutes", merge_lock.DEFAULT_TTL_MINUTES
            )
            _print(
                compose_refusal(
                    acquired,
                    recovery=f"the merge waited the full lock TTL ({ttl} min) and "
                    f"{acquired}. Check that item's merge; rerun this same command "
                    "to wait again, or ask steering to clear a dead holder with --force-lock.",
                ),
                err=True,
            )
            return RECOVERABLE_MERGE_LOCK_EXIT_CODE
        lock_handle = acquired
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
            _print(pf_result[1], err=True)
            exit_code = pf_result[0]
            return exit_code

        # Dirty state
        dirty_result = check_and_clean_root_dirty_state(ctx)
        if dirty_result:
            exit_code = dirty_result[0]
            return exit_code

        prune_agent_worktrees(ctx.repo_root, ctx.args.target)

        # Extract generated files
        ctx.generated_files = extract_generated_files(ctx)

        # Fetch target
        if has_remote(ctx.repo_root):
            _run_git(
                ["fetch", "origin", args.target], cwd=ctx.worktree_path, capture=True
            )

        # Pre-merge main integration
        integration_result = _pre_merge_integration(ctx)
        if integration_result:
            exit_code = integration_result[0]
            return exit_code

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

        mb = _run_git(
            ["merge-base", "HEAD", target_ref(ctx)],
            cwd=ctx.worktree_path,
            capture=True,
        )
        if mb.returncode == 0 and mb.stdout.strip():
            diff = _run_git(
                ["diff", "--name-only", mb.stdout.strip(), "HEAD"],
                cwd=ctx.worktree_path,
                capture=True,
            )
            ctx.branch_changed_files = (
                diff.stdout.strip().splitlines() if diff.stdout.strip() else []
            )

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

        from yoke_core.engines.merge_worktree_recorded_source import (
            record_lane_head_after_merge,
        )

        record_lane_head_after_merge(ctx)

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
            # Committed-merge cleanup already emitted its precise failure.
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
