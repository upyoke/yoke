"""Post-merge cleanup routine for merge-worktree."""

from __future__ import annotations

from pathlib import Path

from yoke_core.engines.merge_worktree_prepare import MergeContext
from yoke_core.engines.merge_worktree_post_helpers import (
    _chdir_out_of_doomed_worktree,
)


def _parent():
    from yoke_core.engines import merge_worktree as _mw
    return _mw

def _post_merge_cleanup(
    ctx: MergeContext,
    no_changes: bool,
    pr_num: str = "",
) -> int:
    """Post-merge verification, worktree removal, sync. Returns exit code.

    The ``Successfully merged`` line is printed HERE, only after the
    origin-ancestry check passes.  Verification failures
    emit ``MergeVerificationFailed`` and exit 1 without cleaning up the
    worktree.  Verification success emits ``MergeVerificationPassed``.
    """
    mw = _parent()
    _print = mw._print
    _run_git = mw._run_git
    _emit_merge_event = mw._emit_merge_event
    # Resolve the post-merge step helpers off the live parent module (mirrors
    # _print / _run_git / _emit_merge_event above) so a monkeypatch on
    # merge_worktree.<helper> is honored by this cleanup routine — the same
    # reason _regenerate_views_or_exit5 itself routes through the parent. Using
    # module-level imports here would bypass those patches and run the real
    # _regenerate_views subprocess during tests.
    _sync_local_target = mw._sync_local_target
    _schema_refresh = mw._schema_refresh
    _regenerate_views_or_exit5 = mw._regenerate_views_or_exit5
    _ensure_target_branch = mw._ensure_target_branch

    _print("")

    if not no_changes:
        _print(f"Verifying merge commit in origin/{ctx.args.target}...")
        _run_git(["fetch", "origin", ctx.args.target], cwd=ctx.repo_root, capture=True)

        branch_tip = _run_git(["rev-parse", ctx.args.branch], cwd=ctx.repo_root, capture=True)
        if branch_tip.returncode == 0 and branch_tip.stdout.strip():
            verify = _run_git(
                ["merge-base", "--is-ancestor", branch_tip.stdout.strip(), f"origin/{ctx.args.target}"],
                cwd=ctx.repo_root, capture=True,
            )
            if verify.returncode != 0:
                _print(
                    f"Error: Branch {ctx.args.branch} tip is not in origin/{ctx.args.target} history.",
                    err=True,
                )
                _print("Worktree preserved for safety.", err=True)
                _emit_merge_event(
                    "MergeVerificationFailed",
                    severity="ERROR",
                    outcome="failure",
                    item_id=ctx.item_id,
                    context={
                        "branch": ctx.args.branch,
                        "target": ctx.args.target,
                        "branch_tip": branch_tip.stdout.strip(),
                        "pr_num": pr_num,
                    },
                )
                return 1
            _print(f"Verified: branch commits present in origin/{ctx.args.target}.")
            _emit_merge_event(
                "MergeVerificationPassed",
                outcome="success",
                item_id=ctx.item_id,
                context={
                    "branch": ctx.args.branch,
                    "target": ctx.args.target,
                    "branch_tip": branch_tip.stdout.strip(),
                    "pr_num": pr_num,
                },
            )
            # Truthful success output -- only after verification passes.
            _print(f"Successfully merged {ctx.args.branch} \u2192 {ctx.args.target}")

    # Worktree and local branch cleanup
    if ctx.worktree_path != ctx.repo_root:
        _chdir_out_of_doomed_worktree(ctx)
        wt_remove = _run_git(
            ["worktree", "remove", "--force", ctx.worktree_path], cwd=ctx.repo_root, capture=True
        )
        if wt_remove.returncode == 0:
            _print(f"Cleaned up worktree: {ctx.worktree_path}")
            # Clean empty parent
            parent = str(Path(ctx.worktree_path).parent)
            if "/.worktrees/" in parent:
                try:
                    if not list(Path(parent).iterdir()):
                        Path(parent).rmdir()
                except OSError:
                    pass
        _run_git(["branch", "-d", ctx.args.branch], cwd=ctx.repo_root, capture=True)

    # Remote branch delete
    if ctx.args.keep_remote:
        _print(f"Skipping remote branch deletion (--keep-remote): {ctx.args.branch}")
    else:
        ls_remote = _run_git(
            ["ls-remote", "--heads", "origin", ctx.args.branch], cwd=ctx.repo_root, capture=True
        )
        if ls_remote.returncode == 0 and ctx.args.branch in (ls_remote.stdout or ""):
            del_result = _run_git(
                ["push", "origin", "--delete", ctx.args.branch], cwd=ctx.repo_root, capture=True
            )
            if del_result.returncode == 0:
                _print(f"Deleted remote branch: {ctx.args.branch}")
            else:
                _print(f"WARNING: Failed to delete remote branch {ctx.args.branch}", err=True)

    # Sync local target with origin (failure -> exit 5)
    sync_ok = _sync_local_target(ctx)
    if not sync_ok:
        _emit_merge_event(
            "MergeEngineFailed",
            severity="ERROR",
            outcome="failure",
            item_id=ctx.item_id,
            context={
                "branch": ctx.args.branch,
                "target": ctx.args.target,
                "epic_id": ctx.epic_id,
                "phase": "post_merge_cleanup",
                "merge_committed": True,
                "exit_code": 5,
                "error_type": "LocalTargetSyncFailed",
                "error": (
                    f"Failed to sync local {ctx.args.target} with origin "
                    f"after PR merge of {ctx.args.branch}"
                ),
            },
        )
        _print("", err=True)
        _print(
            f"Error: local target sync failed after "
            f"{ctx.args.branch} \u2192 {ctx.args.target} was already committed.",
            err=True,
        )
        _print(
            "Phase: post_merge_cleanup (merge already committed \u2014 do NOT "
            "roll the item back to 'implemented').",
            err=True,
        )
        _print(
            "Recovery: from the main repo, run "
            f"`git fetch origin {ctx.args.target}` then "
            f"`git merge --ff-only origin/{ctx.args.target}` if {ctx.args.target} is "
            f"checked out, or `git fetch origin {ctx.args.target}:{ctx.args.target}` "
            f"if it is not; then resume with "
            f"`/yoke usher {(('YOK-' + ctx.item_id) if ctx.item_id else ctx.args.branch)}`.",
            err=True,
        )
        # Continue with remaining cleanup (stash, ensure-target, print
        # YOKE_REPO_ROOT) but return exit 5 at the end.

    # Schema refresh
    _schema_refresh(ctx)

    # Regenerate views -- post-merge-cleanup failure after PR merge
    # landed is its own exit class.  On exit 5 we still run
    # stash cleanup + target-branch pin + print the YOKE_REPO_ROOT
    # contract line so done_transition can re-locate the Yoke repo.
    regen_exit = _regenerate_views_or_exit5(ctx)

    # Stash cleanup
    stash_list = _run_git(["stash", "list"], cwd=ctx.repo_root, capture=True)
    if stash_list.returncode == 0:
        for line in stash_list.stdout.splitlines():
            if f"yoke-pre-rebase-{ctx.args.branch}" in line:
                ref = line.split(":")[0]
                _run_git(["stash", "drop", ref], cwd=ctx.repo_root, capture=True)
                break

    _ensure_target_branch(ctx)

    _print("")
    _print(f"YOKE_REPO_ROOT={ctx.yoke_repo_root}")
    # surface exit 5 from either regen failure or sync failure.
    if regen_exit != 0:
        return regen_exit
    if not sync_ok:
        return 5
    return 0
