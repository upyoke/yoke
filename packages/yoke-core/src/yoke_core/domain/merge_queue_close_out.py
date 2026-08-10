"""What one queue-landed member records once its train lands.

The queue validates a whole train's combined head server-side, so a member's
close-out is bookkeeping rather than work: stamp when it landed, record the
shared verification receipt as covering evidence, and record the merge receipt
that names the two commits this landing is answerable for — the lane head that
entered the queue and the merge commit the queue produced.

That receipt is what lets the item reach its terminal transition at all. The
terminal QA gate compares each blocking run against the heads the merge
boundary recorded, and a queue merge happens entirely on GitHub: no local
commit ever carries it, so without the receipt the gate has nothing to compare
against and every queue-landed item strands.

Nothing here unwinds a landed merge. Each step degrades to a warning, because
the merge has already happened and refusing the bookkeeping would not undo it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from yoke_core.domain import standalone_item_merge_receipt as receipts
from yoke_core.domain.merge_queue_batch_receipt import (
    BatchReceipt,
    observe_batch,
    record_batch_evidence,
)
from yoke_core.domain.standalone_item_merge import stamp_merged_at
from yoke_core.engines.merge_worktree_prepare import MergeContext


@dataclass(frozen=True)
class QueueCloseOut:
    """The bookkeeping one landed queue member produced."""

    merge_sha: str = ""
    batch: Optional[BatchReceipt] = None
    warnings: tuple[str, ...] = field(default=())


def record_landing(
    ctx: MergeContext,
    *,
    item_id: int,
    commit_sha: str,
    pr_num: str,
    member_snapshot: tuple[str, ...] = (),
) -> QueueCloseOut:
    """Record everything the item owes after its train landed."""
    warnings: list[str] = []
    stamp_error = stamp_merged_at(item_id)
    if stamp_error:
        warnings.append(f"merged_at not recorded: {stamp_error}")

    batch, batch_warning = observe_batch(
        ctx, pr_num=pr_num, member_snapshot=member_snapshot
    )
    if batch_warning:
        warnings.append(batch_warning)
    merge_sha = batch.merge_sha if batch is not None else ""
    if batch is not None:
        evidence_error = record_batch_evidence(item_id, batch)
        if evidence_error:
            warnings.append(f"batch evidence not recorded: {evidence_error}")

    receipt_note = receipts.record(
        item_id,
        receipts.MergeReceipt(
            branch=ctx.args.branch,
            target=ctx.args.target,
            commit_sha=commit_sha,
            merge_sha=merge_sha,
        ),
        project=ctx.project,
    )
    if receipt_note:
        warnings.append(receipt_note)
    return QueueCloseOut(
        merge_sha=merge_sha, batch=batch, warnings=tuple(warnings)
    )


__all__ = ["QueueCloseOut", "record_landing"]
