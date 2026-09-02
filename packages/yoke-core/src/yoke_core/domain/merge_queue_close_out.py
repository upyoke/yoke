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
no touched files cannot close out either, so an unreadable pull request is
answered by the second source for the same fact rather than by an empty set:
the first-parent diff of the merge that carried the lane head into the base
branch. GitHub being unreachable is not a reason to strand an item behind a
merge that has already landed.

Physical lane retirement waits for the caller's successful terminal status
transition. A queue landing records the proof that makes the later shared
cleanup safe, but it does not remove the retry lane while evidence or status
gates can still refuse close-out.

Nothing here unwinds a landed merge. Identity and file-recovery failures stay
warnings because refusing them cannot undo it. Missing CI proof is different:
the terminal gate would otherwise call a queue landing ``merged_locally``, so
the caller keeps the item open and retries this bookkeeping instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional

from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain import standalone_item_merge_receipt as receipts
from yoke_core.domain.close_out_control_plane_authority import (
    record_merge_queue_ci_evidence as record_batch_evidence,
)
from yoke_core.domain.merge_queue_batch_receipt import (
    BatchReceipt,
    observe_batch,
)
from yoke_core.domain.standalone_item_merge import stamp_merged_at
from yoke_core.engines.main_checkout_sync import fast_forward_main_checkout
from yoke_core.engines.merge_worktree_pr_files import read_pr_changed_files
from yoke_core.engines.merge_worktree_prepare import MergeContext


@dataclass(frozen=True)
class QueueCloseOut:
    """The bookkeeping one landed queue member produced."""

    merge_sha: str = ""
    touched_files: tuple[str, ...] = field(default=())
    batch: Optional[BatchReceipt] = None
    ci_evidence_error: str = ""
    warnings: tuple[str, ...] = field(default=())

    def ci_evidence_refusal(self, pr_num: str, resume_command: str = "") -> str:
        """Teach the retry that records proof for an irreversible landing."""
        if not self.ci_evidence_error:
            return ""
        recovery = resume_command or "the same yoke merge item command"
        return (
            f"pull request {pr_num} landed, but merge-group CI evidence was "
            f"not recorded: {self.ci_evidence_error}. Re-run {recovery}; the "
            "landing is durable and the retry only closes it out"
        )


def _files_from_merge_commit(
    ctx: MergeContext, commit_sha: str
) -> tuple[str, ...]:
    """What the merge carrying ``commit_sha`` brought into the base branch.

    The second source for the same fact, and the one that survives GitHub
    being unreadable. An evidence record carrying no touched files is refused,
    so a landing whose pull-request read fails would otherwise leave the item
    stranded behind a merge that already happened — the one outcome no retry
    undoes. It reads ``origin/<target>`` rather than the local base branch,
    because the merge happened on GitHub and this checkout need not have it.
    """
    git.fetch_target(ctx.repo_root, ctx.args.target)
    return receipts.touched_files_from_merge_commit(
        ctx.repo_root, f"origin/{ctx.args.target}", commit_sha,
    )


def record_landing(
    ctx: MergeContext,
    *,
    item_id: int,
    commit_sha: str,
    pr_num: str,
    member_snapshot: tuple[str, ...] = (),
    drift_check: Optional[Mapping[str, str]] = None,
) -> QueueCloseOut:
    """Record everything the item owes after its train landed."""
    warnings: list[str] = []
    stamp_error = stamp_merged_at(item_id)
    if stamp_error:
        warnings.append(f"merged_at not recorded: {stamp_error}")

    batch, batch_warning = observe_batch(
        ctx,
        pr_num=pr_num,
        member_snapshot=member_snapshot,
        drift_check=drift_check,
    )
    if batch_warning:
        warnings.append(batch_warning)
    merge_sha = batch.merge_sha if batch is not None else ""
    ci_evidence_error = ""
    if batch is None:
        ci_evidence_error = batch_warning or (
            f"merge-group CI receipt for pull request {pr_num} was not resolved"
        )
    elif not batch.head_sha or not batch.run_url:
        ci_evidence_error = batch_warning or (
            f"merge-group CI receipt for pull request {pr_num} omitted its "
            "verified head or run URL"
        )
    else:
        evidence_error = record_batch_evidence(item_id, batch)
        if evidence_error:
            ci_evidence_error = evidence_error
            warnings.append(f"batch evidence not recorded: {evidence_error}")

    touched, files_error = read_pr_changed_files(ctx, pr_num)
    if files_error:
        warnings.append(f"touched files not resolved: {files_error}")
    elif not touched:
        warnings.append(
            f"pull request {pr_num} reports no changed files"
        )
    touched_files = tuple(touched or ())
    if not touched_files and ctx.repo_root and commit_sha:
        touched_files = _files_from_merge_commit(ctx, commit_sha)
        if touched_files:
            warnings.append(
                f"touched files read from the merge that landed {commit_sha[:12]} "
                f"rather than from pull request {pr_num}"
            )

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

    if ctx.repo_root:
        sync_warning = fast_forward_main_checkout(ctx.repo_root, ctx.args.target)
        if sync_warning:
            warnings.append(sync_warning)
    return QueueCloseOut(
        merge_sha=merge_sha,
        touched_files=touched_files,
        batch=batch,
        ci_evidence_error=ci_evidence_error,
        warnings=tuple(warnings),
    )


__all__ = ["QueueCloseOut", "record_landing"]
