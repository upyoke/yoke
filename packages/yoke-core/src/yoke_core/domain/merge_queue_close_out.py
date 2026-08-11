"""What one queue-landed member records once its train lands.

The queue validates a whole train's combined head server-side, so a member's
close-out is bookkeeping rather than work: stamp when it landed, record the
shared verification receipt as covering evidence, and record the merge receipt
that names what this landing is answerable for — the lane head that entered
the queue, the merge commit the queue produced, and the files the branch
changed.

That receipt is what lets the item reach its terminal transition at all. The
terminal QA gate compares each blocking run against the heads the merge
boundary recorded, and a queue merge happens entirely on GitHub: no local
commit ever carries it, so without the receipt the gate has nothing to compare
against and every queue-landed item strands.

The file set has the same shape of problem and is read the same way. A local
merge diffs the lane against the base it landed on; a queue landing has no
such diff here, because the merge is on GitHub and the head the queue merged
need not be the one this checkout holds. So the files come from the pull
request, which is what GitHub merged. An item whose evidence record carries
no touched files cannot close out either.

Retiring the lane is part of the same bookkeeping. The local engine removes
the worktree it merged from as its last step; a queue landing has no such step
of its own, so it prunes here — and without it every landed member leaves its
directory, its local branch, and its remote branch behind for an operator to
sweep by hand.

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
from yoke_core.engines.merge_landed_lane_cleanup import prune_landed_lane
from yoke_core.engines.main_checkout_sync import fast_forward_main_checkout
from yoke_core.engines.merge_worktree_pr_files import read_pr_changed_files
from yoke_core.engines.merge_worktree_prepare import MergeContext


@dataclass(frozen=True)
class QueueCloseOut:
    """The bookkeeping one landed queue member produced."""

    merge_sha: str = ""
    touched_files: tuple[str, ...] = field(default=())
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

    touched, files_error = read_pr_changed_files(ctx, pr_num)
    if files_error:
        warnings.append(f"touched files not resolved: {files_error}")
    elif not touched:
        warnings.append(
            f"pull request {pr_num} reports no changed files"
        )
    touched_files = tuple(touched or ())

    receipt_note = receipts.record(
        item_id,
        receipts.MergeReceipt(
            branch=ctx.args.branch,
            target=ctx.args.target,
            commit_sha=commit_sha,
            merge_sha=merge_sha,
            touched_files=touched_files,
        ),
        project=ctx.project,
    )
    if receipt_note:
        warnings.append(receipt_note)

    # A context carrying no repository root belongs to a caller with no local
    # checkout to prune, so there is no lane here to leave behind.
    if ctx.repo_root:
        warnings.extend(
            prune_landed_lane(
                repo_root=ctx.repo_root,
                branch=ctx.args.branch,
                target=ctx.args.target,
                item_id=item_id,
            )
        )
        sync_warning = fast_forward_main_checkout(ctx.repo_root, ctx.args.target)
        if sync_warning:
            warnings.append(sync_warning)
    return QueueCloseOut(
        merge_sha=merge_sha,
        touched_files=touched_files,
        batch=batch,
        warnings=tuple(warnings),
    )


__all__ = ["QueueCloseOut", "record_landing"]
