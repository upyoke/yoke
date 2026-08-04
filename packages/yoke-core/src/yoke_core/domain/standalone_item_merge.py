"""The one merge boundary for an item branch that owns no epic lane.

Every standalone item branch — Dash, Blitz, and any Issue whose workflow
generates no task graph — lands on its project base branch through
:func:`merge_standalone_branch`. The function owns the merge itself and the
bookkeeping the merge produces (identity resolution, the ``merged_at`` stamp,
publishing the base branch, the durable receipt a retry converges from,
telemetry). Item bookkeeping that differs by workflow — execution evidence,
GitHub sync, the lifecycle status flip — stays with the caller so it runs
through the item's own gates.

The reads live in :mod:`yoke_core.domain.standalone_item_merge_git` and the
receipt in :mod:`yoke_core.domain.standalone_item_merge_receipt`, because
what git can answer changes as the merge proceeds while the receipt does not.

Rationale and portability constraints: ``docs/archive/decisions/
standalone-item-merge.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Sequence

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain import standalone_item_merge_receipt as receipts
from yoke_core.domain.standalone_item_merge_engine import run as _run_merge_engine

# Exit code for a merge the engine refused because another session holds the
# merge lock. Mirrors the engine's own retryable class so callers can
# distinguish "try again later" from "this merge is wrong".
RECOVERABLE_MERGE_LOCK_EXIT_CODE = 6


@dataclass(frozen=True)
class StandaloneMergeOutcome:
    """What one standalone merge attempt produced."""

    ok: bool
    exit_code: int
    already_merged: bool
    commit_sha: str = ""
    merge_sha: str = ""
    touched_files: tuple[str, ...] = ()
    pushed: bool = False
    error: str = ""
    output: str = ""
    warnings: tuple[str, ...] = field(default=())


def stamp_merged_at(item_id: int) -> Optional[str]:
    """Record when the branch landed. Returns an error string on failure."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    response = call_dispatcher(
        function_id="done_transition.populate_merged_at",
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload={"merged_at": now},
    )
    if response.success:
        return None
    return (
        response.error.message if response.error is not None
        else "merged_at write failed"
    )


def _complete(
    *,
    item_id: int,
    branch: str,
    target: str,
    repo_root: str,
    project: str,
    commit_sha: str,
    touched: tuple[str, ...],
    already: bool,
    output: str = "",
    warnings: Sequence[str] = (),
) -> StandaloneMergeOutcome:
    """Publish, stamp, and record the completed receipt for a landed merge."""
    merge_sha = git.git_out(repo_root, "rev-parse", target)
    notes = list(warnings)
    pushed, push_warning = git.publish(repo_root, target)
    if push_warning:
        notes.append(push_warning)
    stamp_error = stamp_merged_at(item_id)
    if stamp_error:
        notes.append(f"merged_at not recorded: {stamp_error}")
    receipt_note = receipts.record(
        item_id,
        receipts.MergeReceipt(
            branch=branch,
            target=target,
            commit_sha=commit_sha,
            merge_sha=merge_sha,
            touched_files=touched,
        ),
        project=project,
    )
    if receipt_note:
        notes.append(receipt_note)
    return StandaloneMergeOutcome(
        ok=True,
        exit_code=0,
        already_merged=already,
        commit_sha=commit_sha,
        merge_sha=merge_sha,
        touched_files=touched,
        pushed=pushed,
        output=output,
        warnings=tuple(notes),
    )


def _converge_from_receipt(
    *,
    item_id: int,
    branch: str,
    target: str,
    repo_root: str,
    project: str,
    recorded: Optional[receipts.MergeReceipt],
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
        commit_sha=recorded.commit_sha,
        touched=receipts.resolve_touched_files(
            repo_root=repo_root,
            target=target,
            commit_sha=recorded.commit_sha,
            recorded=recorded,
            observed=(),
        ),
        already=True,
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
) -> StandaloneMergeOutcome:
    """Land one standalone item branch on ``target`` and stamp the item.

    Convergent under interruption. The engine's cleanup deletes the branch ref
    and removes the lane, which destroys the git state this function would
    otherwise re-derive its bookkeeping from, so the bookkeeping is recorded as
    a durable receipt *before* the engine runs. A retry then converges on the
    same completed state from the receipt: with the ref gone it finishes the
    close-out outright, and with the branch already contained by ``target`` it
    resolves the touched files from the recorded merge identity instead of the
    empty diff git now reports.

    An engine that raises after the merge has landed — the cleanup order that
    removes the lane the running process imports from — is likewise treated as
    a landed merge rather than losing it, so the item still gets its evidence
    and its terminal transition.

    Merge telemetry (``MergeEngineStarted`` and its outcome) is emitted by the
    engine this delegates to, so a standalone merge is visible in the events
    ledger for the same reason an epic-lane merge is.
    """
    recorded = receipts.load(item_id, branch, target, project=project)
    if not git.branch_exists(repo_root, branch):
        return _converge_from_receipt(
            item_id=item_id,
            branch=branch,
            target=target,
            repo_root=repo_root,
            project=project,
            recorded=recorded,
        )

    if not commit_sha:
        return StandaloneMergeOutcome(
            ok=False,
            exit_code=1,
            already_merged=False,
            error=f"active lane for branch '{branch}' has no recorded HEAD",
        )
    observed = git.changed_files(repo_root, commit_sha, target)
    already = git.is_ancestor(repo_root, commit_sha, target)

    output = ""
    warnings: list[str] = []
    if not already:
        receipt_note = receipts.record(
            item_id,
            receipts.MergeReceipt(
                branch=branch,
                target=target,
                commit_sha=commit_sha,
                touched_files=observed,
            ),
            project=project,
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
                        "merge lock held by another session; retry once it clears"
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
    )


def sync_item_to_github(item_id: int) -> Optional[str]:
    """Mirror the item to GitHub when its project's sync mode allows it.

    The sync owner already skips projects that do not mirror, so this call is
    unconditional; the return value is advisory and never unwinds a merge.
    """
    response = call_dispatcher(
        function_id="items.github_sync",
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload={},
    )
    if response.success:
        return None
    return (
        response.error.message if response.error is not None
        else "GitHub sync failed"
    )


__all__ = [
    "RECOVERABLE_MERGE_LOCK_EXIT_CODE",
    "StandaloneMergeOutcome",
    "merge_standalone_branch",
    "stamp_merged_at",
    "sync_item_to_github",
]
