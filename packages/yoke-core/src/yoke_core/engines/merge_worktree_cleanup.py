"""Post-merge cleanup routine for merge-worktree."""

from __future__ import annotations


from yoke_contracts.codex_hook_trust_store import worktree_cleanup_warning
from yoke_core.domain.public_item_target import public_item_target
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
    # merge_worktree.<helper> is honored by this cleanup routine. Module-level
    # imports here would bypass those patches.
    _sync_local_target = mw._sync_local_target
    _schema_refresh = mw._schema_refresh
    _ensure_target_branch = mw._ensure_target_branch

    _print("")

    from yoke_core.domain.merge_landing_proof import (
        LandingUnverified,
        verified_target_sha,
    )

    candidate = mw._run_git(
        ["rev-parse", ctx.args.branch], cwd=ctx.repo_root, capture=True
    )
    candidate_sha = (
        candidate.stdout.strip() if candidate.returncode == 0 else ctx.args.source_sha
    )
    try:
        remote_sha = verified_target_sha(ctx.repo_root, ctx.args.target, candidate_sha)
    except LandingUnverified as exc:
        _print(str(exc), err=True)
        _emit_merge_event(
            "MergeVerificationFailed",
            severity="ERROR",
            outcome="failure",
            item_id=ctx.item_id,
            context={
                "branch": ctx.args.branch,
                "target": ctx.args.target,
                "error": str(exc),
            },
        )
        return 1
    _print(
        f"Verified: candidate {candidate_sha} is present in remote target {remote_sha}."
    )
    _emit_merge_event(
        "MergeVerificationPassed",
        outcome="success",
        item_id=ctx.item_id,
        context={
            "branch": ctx.args.branch,
            "target": ctx.args.target,
            "branch_tip": candidate_sha,
            "remote_sha": remote_sha,
            "pr_num": pr_num,
        },
    )
    from yoke_core.engines.merge_worktree_landing import record_worktree_landing

    if not record_worktree_landing(
        ctx, candidate_sha=candidate_sha, target_sha=remote_sha, pr_num=pr_num
    ):
        return 5
    _print(f"Successfully merged {ctx.args.branch} → {ctx.args.target}")
    if ctx.args.standalone:
        if not _sync_local_target(ctx):
            _print(
                "merge_target_sync_failed: landing is proven; preserve the lane and retry the governed merge command after repairing local target synchronization.",
                err=True,
            )
            return 5
        _schema_refresh(ctx)
        _ensure_target_branch(ctx)
        _print(f"YOKE_REPO_ROOT={ctx.yoke_repo_root}")
        return 0

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
        from yoke_core.engines.lane_residue_declared_paths import (
            declared_disposable_roots_for_project,
        )
        from yoke_core.engines.merge_worktree_cleanliness import clear_lane_residue

        residue = clear_lane_residue(
            _run_git,
            ctx.worktree_path,
            declared_disposable_roots_for_project(ctx.project),
        )
        removal = None
        if not residue.removable_once_landed:
            _print(
                f"WARNING: Preserving worktree {ctx.worktree_path}: {residue.reason}",
                err=True,
            )
        else:
            from yoke_core.engines.worktree_removal import remove_worktree

            removal = remove_worktree(ctx.repo_root, ctx.worktree_path)
            worktree_removed = removal.removed
        if worktree_removed:
            _print(f"Cleaned up worktree: {ctx.worktree_path}")
            if removal is not None and removal.reason:
                _print(f"WARNING: {removal.reason}", err=True)
            if warning := worktree_cleanup_warning(ctx.worktree_path):
                _print(f"WARNING: {warning}", err=True)
            _release_lane_row(ctx)
        elif removal is not None:
            _print(
                f"WARNING: Worktree removal refused ({removal.reason}); preserving "
                f"branch {ctx.args.branch}",
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
            public_item_target(ctx.item_id).public_ref
            if ctx.item_id
            else ctx.args.branch
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
