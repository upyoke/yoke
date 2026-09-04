"""Post-merge cleanup routine for merge-worktree."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.codex_hook_trust_store import worktree_cleanup_warning
from yoke_core.domain.project_identity_item_ref import item_ref_for_id
from yoke_core.domain.worktree_import_reseat import reseat_loaded_packages
from yoke_core.engines.merge_landed_lane_cleanup import release_lane_row
from yoke_core.engines.merge_worktree_prepare import MergeContext
from yoke_core.engines.merge_worktree_post_helpers import (
    _chdir_out_of_doomed_worktree,
)
from yoke_core.engines.remote_branch_cleanup import (
    delete_remote_branch_if_merged,
)


def _parent():
    from yoke_core.engines import merge_worktree as _mw

    return _mw


def _release_lane_row(ctx: MergeContext) -> None:
    """Retire the lane row for the worktree this cleanup just removed."""
    release_lane_row(ctx.item_id, ctx.args.branch, emit=_parent()._print)


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
    # reason _regenerate_views_advisory itself routes through the parent. Using
    # module-level imports here would bypass those patches and run the real
    # _regenerate_views subprocess during tests.
    _sync_local_target = mw._sync_local_target
    _schema_refresh = mw._schema_refresh
    _regenerate_views_advisory = mw._regenerate_views_advisory
    _ensure_target_branch = mw._ensure_target_branch

    _print("")

    if not no_changes:
        _print(f"Verifying merge commit in origin/{ctx.args.target}...")
        _run_git(["fetch", "origin", ctx.args.target], cwd=ctx.repo_root, capture=True)

        branch_tip = _run_git(
            ["rev-parse", ctx.args.branch], cwd=ctx.repo_root, capture=True
        )
        if branch_tip.returncode == 0 and branch_tip.stdout.strip():
            verify = _run_git(
                [
                    "merge-base",
                    "--is-ancestor",
                    branch_tip.stdout.strip(),
                    f"origin/{ctx.args.target}",
                ],
                cwd=ctx.repo_root,
                capture=True,
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

    # Prove and delete the remote branch before discarding the local retry
    # lane. An ambiguous, concurrently updated, unmerged, or refused remote
    # delete leaves the worktree and local branch in place for inspection and
    # a later safe retry.
    local_cleanup_safe = True
    if ctx.args.keep_remote:
        _print(f"Skipping remote branch deletion (--keep-remote): {ctx.args.branch}")
    else:
        remote_result = delete_remote_branch_if_merged(
            run_git=lambda command: _run_git(
                command,
                cwd=ctx.repo_root,
                capture=True,
            ),
            branch=ctx.args.branch,
            target_branch=ctx.args.target,
        )
        local_cleanup_safe = remote_result.cleanup_complete
        if remote_result.status == "deleted":
            _print(f"Deleted remote branch: {ctx.args.branch}")
        elif remote_result.status == "preserved":
            _print(
                f"WARNING: Preserving remote branch {ctx.args.branch}: "
                f"{remote_result.reason}",
                err=True,
            )

    # Worktree cleanup. Local branch deletion waits until the target branch is
    # synchronized below so normal ``git branch -d`` can prove ancestry against
    # the checked-out target without force.
    worktree_removed = False
    if not local_cleanup_safe:
        _print(
            "WARNING: Preserving local worktree and branch so remote cleanup "
            "can be retried safely.",
            err=True,
        )
    elif ctx.worktree_path != ctx.repo_root:
        _chdir_out_of_doomed_worktree(ctx)
        # The close-out this merge still owes — GitHub sync, board rebuild,
        # the terminal transition — issues lazy imports after this point. When
        # the process loaded its own packages out of the lane, those imports
        # resolve against a directory that is about to stop existing, so they
        # are repointed at the surviving checkout while it is still possible.
        reseat_loaded_packages(
            doomed_root=ctx.worktree_path,
            surviving_root=ctx.repo_root,
        )
        from yoke_core.engines.merge_worktree_cleanliness import (
            clean_after_disposable_cache_removal,
        )

        worktree_clean = clean_after_disposable_cache_removal(
            _run_git, ctx.worktree_path
        )
        if not worktree_clean:
            _print(
                f"WARNING: Preserving dirty or unverifiable worktree: "
                f"{ctx.worktree_path}",
                err=True,
            )
        else:
            wt_remove = _run_git(
                ["worktree", "remove", ctx.worktree_path],
                cwd=ctx.repo_root,
                capture=True,
            )
            worktree_removed = wt_remove.returncode == 0
        if worktree_removed:
            _print(f"Cleaned up worktree: {ctx.worktree_path}")
            if warning := worktree_cleanup_warning(ctx.worktree_path):
                _print(f"WARNING: {warning}", err=True)
            _release_lane_row(ctx)
            # Clean empty parent
            parent = str(Path(ctx.worktree_path).parent)
            if "/.worktrees/" in parent:
                try:
                    if not list(Path(parent).iterdir()):
                        Path(parent).rmdir()
                except OSError:
                    pass
        elif worktree_clean:
            _print(
                f"WARNING: Worktree removal refused; preserving branch "
                f"{ctx.args.branch}",
                err=True,
            )

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
        usher_ref = (
            item_ref_for_id(int(ctx.item_id)) if ctx.item_id else ctx.args.branch
        )
        _print(
            "Recovery: from the main repo, run "
            f"`git fetch origin {ctx.args.target}` then "
            f"`git merge --ff-only origin/{ctx.args.target}` if {ctx.args.target} is "
            f"checked out, or `git fetch origin {ctx.args.target}:{ctx.args.target}` "
            f"if it is not; then resume with "
            f"`/yoke usher {usher_ref}`.",
            err=True,
        )
        # Continue with remaining cleanup (stash, ensure-target, print
        # YOKE_REPO_ROOT) but return exit 5 at the end.

    if sync_ok and worktree_removed:
        branch_delete = _run_git(
            ["branch", "-d", ctx.args.branch],
            cwd=ctx.repo_root,
            capture=True,
        )
        if branch_delete.returncode != 0:
            _print(
                f"WARNING: Preserving local branch after delete refusal: "
                f"{ctx.args.branch}",
                err=True,
            )

    # Schema refresh
    _schema_refresh(ctx)

    # Generated views are advisory after the merge has landed. Retry once and
    # defer any persistent failure without blocking terminal close-out.
    _regenerate_views_advisory(ctx)

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
    if not sync_ok:
        return 5
    return 0
