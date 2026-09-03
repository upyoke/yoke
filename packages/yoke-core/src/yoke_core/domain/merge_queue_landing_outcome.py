"""What a queue landing reports, and how a landed member closes out into it.

Two routes reach the same ending. One waits for the merge in its own
process; the other finds the landing already recorded on the item, because
the control-plane observer
(:mod:`yoke_core.domain.merge_queue_landing_observer`) saw it happen while
nothing was waiting. Both converge on ``close_out`` so the receipts,
evidence, and warnings an item carries do not depend on who noticed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.merge_queue_batch_receipt import BatchReceipt
from yoke_core.domain.merge_queue_close_out import record_landing
from yoke_core.domain.merge_queue_drift_gate import drift_receipt
from yoke_core.domain.merge_queue_landing_wait import RECOVERABLE_QUEUE_EXIT_CODE
from yoke_core.engines.merge_worktree_prepare import MergeContext


@dataclass(frozen=True)
class QueueLandingOutcome:
    ok: bool
    exit_code: int
    pr_num: str = ""
    commit_sha: str = ""
    merge_sha: str = ""
    touched_files: tuple[str, ...] = field(default=())
    batch: Optional[BatchReceipt] = None
    already_merged: bool = False
    landing_pending: bool = False
    enqueued_at: str = ""
    error: str = ""
    warnings: tuple[str, ...] = field(default=())


def fail_landing(
    pr_num: str, error: str, warnings, *, exit_code: int = 1
) -> QueueLandingOutcome:
    return QueueLandingOutcome(
        ok=False, exit_code=exit_code, pr_num=pr_num, error=error, warnings=warnings
    )


def recorded_landing(dispatch: Callable[..., Any], item_id: int) -> tuple[str, str]:
    """The pull request and landing time already recorded, if any.

    Read through the registered item detail so the answer follows the
    active control-plane transport. An unreadable read answers "nothing
    recorded", which puts the caller back on the full landing path — the
    same work it would have done anyway.
    """
    response = dispatch(
        function_id="items.detail.get",
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload={},
    )
    if not getattr(response, "success", False):
        return "", ""
    result = getattr(response, "result", None) or {}
    queue = (result.get("item") or {}).get("merge_queue") or {}
    return str(queue.get("pr_number") or ""), str(queue.get("landed_at") or "")


def close_out(
    ctx: MergeContext,
    *,
    item_id: int,
    public_ref: str,
    commit_sha: str,
    pr_num: str,
    member_refs: tuple[str, ...],
    drift: Any,
    resume_command: str,
    warnings: list[str],
    already_merged: bool = True,
) -> QueueLandingOutcome:
    """Record what a landed member owes, from either landing route.

    Missing CI proof is the one recoverable refusal: re-running only
    repeats this bookkeeping, because the merge itself is already durable.
    """
    recorded = record_landing(
        ctx,
        item_id=item_id,
        commit_sha=commit_sha,
        pr_num=pr_num,
        member_snapshot=tuple(dict.fromkeys((*member_refs, public_ref))),
        drift_check=drift_receipt(drift) if drift is not None else None,
    )
    warnings.extend(recorded.warnings)
    ci_refusal = recorded.ci_evidence_refusal(pr_num, resume_command)
    if ci_refusal:
        return fail_landing(
            pr_num,
            ci_refusal,
            tuple(warnings),
            exit_code=RECOVERABLE_QUEUE_EXIT_CODE,
        )
    return QueueLandingOutcome(
        ok=True,
        exit_code=0,
        pr_num=pr_num,
        commit_sha=commit_sha,
        merge_sha=recorded.merge_sha,
        touched_files=recorded.touched_files,
        batch=recorded.batch,
        already_merged=already_merged,
        warnings=tuple(warnings),
    )


__all__ = [
    "QueueLandingOutcome",
    "close_out",
    "fail_landing",
    "recorded_landing",
]
