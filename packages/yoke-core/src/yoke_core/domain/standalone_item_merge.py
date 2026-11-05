"""The one merge boundary for an item branch that owns no epic lane.

Every standalone item branch — Dash, Blitz, and any Issue whose workflow
generates no task graph — lands on its project base branch through
:func:`merge_standalone_branch`. The function owns the merge itself and the
bookkeeping the merge produces (identity resolution, the ``merged_at`` stamp
carrying the landing merge commit's own time,
publishing the base branch, the durable receipt a retry converges from,
telemetry). Item bookkeeping that differs by workflow — execution evidence,
GitHub sync, the lifecycle status flip — stays with the caller so it runs
through the item's own gates.

The reads live in :mod:`yoke_core.domain.standalone_item_merge_git` and the
receipt in :mod:`yoke_core.domain.item_merge_receipts`, because
what git can answer changes as the merge proceeds while the receipt does not.

Rationale and portability constraints: ``docs/archive/decisions/
standalone-item-merge.md``.
"""

from __future__ import annotations

from yoke_contracts.timestamps import format_instant, utc_now

from yoke_core.domain.public_item_target import public_item_target

from typing import Optional, Sequence

from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain.merge_github_authority import classify_merge_authority
from yoke_core.domain import standalone_item_merge_post_push as post_push
from yoke_core.domain import item_merge_receipts as receipts
from yoke_core.domain.standalone_item_merge_engine import run as _run_merge_engine
from yoke_core.domain.standalone_item_merge_outcome import (
    StandaloneMergeOutcome,
    sync_item_to_github,
)

# Exit code for a merge the engine refused because another session holds the
# merge lock. Mirrors the engine's own retryable class so callers can
# distinguish "try again later" from "this merge is wrong".
RECOVERABLE_MERGE_LOCK_EXIT_CODE = 6


def stamp_merged_at(
    item_id: int, *, repo_root: str = "", merge_sha: str = ""
) -> Optional[str]:
    """Record when the branch landed. Returns an error string on failure.

    The landing merge commit has a time of its own, read here from the
    checkout that just merged it. That is a fact about the landing rather
    than the moment close-out reached this line, so it supersedes whatever
    the item recorded: an item that lands a second time must stop reporting
    the first landing's date, and a close-out re-entered hours later must
    write the same answer rather than a fresher, falser one.

    A landing with no readable merge commit -- a fast-forward, or a checkout
    that cannot answer -- falls back to now and keeps any earlier answer,
    because "now" is only ever an approximation of a landing nobody timed.
    """
    landed_at = git.commit_time(repo_root, merge_sha) if repo_root else None
    clock = utc_now() if landed_at is None else landed_at
    response = call_dispatcher(
        function_id="done_transition.populate_merged_at",
        target=public_item_target(item_id),
        payload={
            "merged_at": format_instant(clock),
            "supersedes_prior_landing": landed_at is not None,
        },
    )
    if response.success:
        return None
    return (
        response.error.message
        if response.error is not None
        else "merged_at write failed"
    )


def _complete(
    *,
    item_id: int,
    branch: str,
    target: str,
    repo_root: str,
    project: str,
    authority: str,
    commit_sha: str,
    touched: tuple[str, ...],
    already: bool,
    output: str = "",
    warnings: Sequence[str] = (),
    resume_command: str = "",
) -> StandaloneMergeOutcome:
    """Publish, stamp, and record the completed receipt for a landed merge."""
    return post_push.complete(
        item_id=item_id,
        branch=branch,
        target=target,
        repo_root=repo_root,
        project=project,
        authority=authority,
        commit_sha=commit_sha,
        touched=touched,
        already=already,
        output=output,
        warnings=warnings,
        resume_command=resume_command,
    )


def _converge_from_receipt(
    *,
    item_id: int,
    branch: str,
    target: str,
    repo_root: str,
    project: str,
    authority: str,
    recorded: Optional[receipts.MergeReceipt],
    resume_command: str = "",
) -> StandaloneMergeOutcome:
    """Finish a merge whose branch ref the engine's cleanup already deleted."""
    if recorded is None or not recorded.commit_sha:
        return StandaloneMergeOutcome(
            ok=False,
            exit_code=1,
            already_merged=False,
            error=(
                f"branch '{branch}' does not exist in {repo_root} and no "
                f"merge receipt records it landing on '{target}'"
            ),
        )
    if not git.is_ancestor(repo_root, recorded.commit_sha, target):
        return StandaloneMergeOutcome(
            ok=False,
            exit_code=1,
            already_merged=False,
            commit_sha=recorded.commit_sha,
            error=(
                f"branch '{branch}' is gone from {repo_root} and its recorded "
                f"commit {recorded.commit_sha} is not contained by '{target}'"
            ),
        )
    return _complete(
        item_id=item_id,
        branch=branch,
        target=target,
        repo_root=repo_root,
        project=project,
        authority=authority,
        commit_sha=recorded.commit_sha,
        touched=receipts.resolve_touched_files(
            repo_root=repo_root,
            target=target,
            commit_sha=recorded.commit_sha,
            recorded=recorded,
            observed=(),
        ),
        already=True,
        resume_command=resume_command,
    )


def merge_standalone_branch(
    *,
    item_id: int,
    branch: str,
    commit_sha: str = "",
    target: str,
    repo_root: str,
    project: str,
    local_merge: bool = True,
    resume_command: str = "",
) -> StandaloneMergeOutcome:
    from dataclasses import replace
    from yoke_core.domain import standalone_item_merge_pin_refresh as refresh

    warnings = []
    for attempt in range(refresh.PIN_REFRESH_ATTEMPTS + 1):
        outcome = _merge_once(
            item_id=item_id,
            branch=branch,
            commit_sha=commit_sha,
            target=target,
            repo_root=repo_root,
            project=project,
            local_merge=local_merge,
            resume_command=resume_command,
        )
        if (
            not outcome.error.startswith("merge_target_moved:")
            or attempt == refresh.PIN_REFRESH_ATTEMPTS
            or not refresh.pin_only_advance(repo_root, target)
        ):
            return replace(outcome, warnings=tuple(warnings) + outcome.warnings)
        pins = git.git_out(
            repo_root, "log", "--format=%s", f"{target}..origin/{target}"
        )
        try:
            retained = refresh.reset_target_to_origin(repo_root, branch, target)
        except RuntimeError as exc:
            return replace(outcome, warnings=tuple(warnings) + (str(exc),))
        warnings.append(
            f"Retained unpublished merge on {retained}; retrying over release pins: {pins}"
        )
        commit_sha = git.head_of(repo_root, branch)
    return outcome


def _merge_once(
    *,
    item_id: int,
    branch: str,
    commit_sha: str = "",
    target: str,
    repo_root: str,
    project: str,
    local_merge: bool = True,
    resume_command: str = "",
) -> StandaloneMergeOutcome:
    """Land one branch, retaining its lane until proof and close-out succeed.

    Durable receipts converge interrupted attempts. A cleanup error after
    landing does not erase the landing; the engine owns merge telemetry.
    """
    # The route decides the authority, and the proof after the merge reads
    # checks under that same one rather than the strictest available.
    authority = classify_merge_authority(local_merge=local_merge).authority
    recorded = receipts.load(item_id, branch, target)
    if not git.branch_exists(repo_root, branch):
        return _converge_from_receipt(
            item_id=item_id,
            branch=branch,
            target=target,
            repo_root=repo_root,
            project=project,
            authority=authority,
            recorded=recorded,
            resume_command=resume_command,
        )

    output = ""
    warnings: list[str] = []
    if not commit_sha:
        # Derive the lane head until serving can record it.
        commit_sha = git.head_of(repo_root, branch)
        if not commit_sha:
            return StandaloneMergeOutcome(
                ok=False,
                exit_code=1,
                already_merged=False,
                error=(
                    f"active lane for branch '{branch}' has no recorded HEAD "
                    f"and '{branch}' could not be resolved in {repo_root}"
                ),
            )
        warnings.append(
            f"lane head not recorded by the control plane; using {branch} at "
            f"{commit_sha[:12]}. The control plane records it once it is "
            "deployed on a build carrying item_worktrees.commit_sha."
        )
    base = git.current_base_ref(repo_root, target)
    observed = git.changed_files(repo_root, commit_sha, base)
    already = git.is_ancestor(repo_root, commit_sha, base)
    if not already:
        receipt_note = receipts.record_before_landing(
            item_id,
            repo_root=repo_root,
            branch=branch,
            target=target,
            commit_sha=commit_sha,
            touched_files=observed,
        )
        if receipt_note:
            warnings.append(receipt_note)
        try:
            exit_code, output = _run_merge_engine(
                item_id=item_id,
                repo_root=repo_root,
                branch=branch,
                source_sha=commit_sha,
                target=target,
                local_merge=local_merge,
            )
        except Exception as exc:  # noqa: BLE001 - a landed merge outranks it
            if not git.is_ancestor(repo_root, commit_sha, target):
                return StandaloneMergeOutcome(
                    ok=False,
                    exit_code=1,
                    already_merged=False,
                    commit_sha=commit_sha,
                    touched_files=observed,
                    error=f"merge engine raised before the branch landed: {exc}",
                )
            warnings.append(
                f"merge landed; the engine then raised during cleanup: {exc}"
            )
        else:
            if exit_code != 0:
                return StandaloneMergeOutcome(
                    ok=False,
                    exit_code=exit_code,
                    already_merged=False,
                    commit_sha=commit_sha,
                    touched_files=observed,
                    error=(
                        f"merge lock wait timed out: {output.strip()}; check the holding item’s merge, then rerun"
                        if exit_code == RECOVERABLE_MERGE_LOCK_EXIT_CODE
                        else f"merge engine exited {exit_code}"
                    ),
                    output=output,
                )

    return _complete(
        item_id=item_id,
        branch=branch,
        target=target,
        repo_root=repo_root,
        project=project,
        authority=authority,
        commit_sha=commit_sha,
        touched=receipts.resolve_touched_files(
            repo_root=repo_root,
            target=target,
            commit_sha=commit_sha,
            recorded=recorded,
            observed=observed,
        ),
        already=already,
        output=output,
        warnings=warnings,
        resume_command=resume_command,
    )


__all__ = [
    "RECOVERABLE_MERGE_LOCK_EXIT_CODE",
    "StandaloneMergeOutcome",
    "merge_standalone_branch",
    "stamp_merged_at",
    "sync_item_to_github",
]
