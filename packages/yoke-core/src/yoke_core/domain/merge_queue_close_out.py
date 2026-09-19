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

Which pull request the item points at is settled here too. The marker names
the pull request the item last armed, and a lane whose commits reached the
base under a sibling one leaves its own open forever; close-out knows the
merge the base actually holds, so it repoints the marker at the pull request
that merge carried (:mod:`yoke_core.domain.merge_queue_landing_carrier`). An
ordinary landing finds the marker already right and writes nothing.

Physical lane retirement waits for the caller's successful terminal status
transition. A queue landing records the proof that makes the later shared
cleanup safe, but it does not remove the retry lane while evidence or status
gates can still refuse close-out.

Nothing here unwinds a landed merge. Identity and file-recovery failures stay
warnings because refusing them cannot undo it. Missing CI proof is different:
the terminal gate would otherwise call a queue landing ``merged_locally``, so
the caller keeps the item open and retries this bookkeeping instead.

The CI proof comes off a ladder, recorded rung first. This runs once when the
train lands and again at the deployment wake, and only the first of those is
close enough to the train for GitHub's ``merge_group`` runs to be the easy
answer. So the second reads the receipt the first recorded. Deriving it again
from the provider is the fallback, not the default: it can only agree with
the item's own landing or fail, and members whose proof was sitting in their
own QA rows were stranded for the difference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional

from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain import item_merge_receipts as receipts
from yoke_core.domain.close_out_control_plane_authority import (
    record_merge_queue_ci_evidence as record_batch_evidence,
    recorded_merge_queue_ci_evidence as read_recorded_batch,
)
from yoke_core.domain.merge_queue_batch_receipt import (
    BatchReceipt,
    observe_batch,
)
from yoke_core.domain.merge_queue_landing_carrier import (
    repoint_to_landing_carrier,
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
    # Whether running this same close-out again could reach a different
    # answer. A failure that cannot is the one a blanket "re-run it" turns
    # into an unbounded loop, so the refusal reads this rather than assuming.
    ci_evidence_retryable: bool = True
    ci_evidence_recovery: str = ""
    warnings: tuple[str, ...] = field(default=())

    def ci_evidence_refusal(self, pr_num: str, resume_command: str = "") -> str:
        """Name the recovery for a landing whose proof was not recorded."""
        if not self.ci_evidence_error:
            return ""
        # Deliberately does not say the pull request landed: a lane whose
        # commits reached the base under a companion item's train leaves its
        # own pull request open, and asserting otherwise sends the reader
        # looking for a merge that never happened.
        preamble = (
            f"the base already holds this lane's work, but merge-group CI "
            f"evidence was not recorded for pull request {pr_num}: "
            f"{self.ci_evidence_error}"
        )
        if not self.ci_evidence_retryable:
            detail = (
                f". {self.ci_evidence_recovery}" if self.ci_evidence_recovery else ""
            )
            return (
                f"{preamble}{detail} The landing is durable; running this "
                "close-out again reaches the same answer, so it is not the "
                "recovery"
            )
        recovery = resume_command or "the same yoke merge item command"
        detail = f" {self.ci_evidence_recovery}" if self.ci_evidence_recovery else ""
        return (
            f"{preamble}.{detail} Re-run {recovery}; the landing is durable "
            "and the retry only closes it out"
        )


def _files_from_merge_commit(
    ctx: MergeContext, commit_sha: str, state: dict
) -> tuple[str, ...]:
    """What the merge carrying ``commit_sha`` brought into the base branch.

    The second source for the same fact, and the one that survives GitHub
    being unreadable. An evidence record carrying no touched files is refused,
    so a landing whose pull-request read fails would otherwise leave the item
    stranded behind a merge that already happened — the one outcome no retry
    undoes. It reads ``origin/<target>`` rather than the local base branch,
    because the merge happened on GitHub and this checkout need not have it.
    """
    _fetch_once(ctx, state)
    return receipts.touched_files_from_merge_commit(
        ctx.repo_root, f"origin/{ctx.args.target}", commit_sha,
    )


def _fetch_once(ctx: MergeContext, state: dict) -> None:
    """Refresh ``origin/<target>`` at most once per close-out."""
    if state.get("fetched"):
        return
    state["fetched"] = True
    git.fetch_target(ctx.repo_root, ctx.args.target)


def _landing_merge(ctx: MergeContext, commit_sha: str, state: dict) -> str:
    """The merge that carried ``commit_sha`` into the base branch.

    The pointer an item records names the pull request it last armed, which
    a re-arm can move to one that never merges. This is the fact that does
    not drift: whatever merge the base actually holds this work under.
    """
    if not ctx.repo_root or not commit_sha:
        return ""
    try:
        _fetch_once(ctx, state)
        return receipts.landing_merge_commit(
            ctx.repo_root, f"origin/{ctx.args.target}", commit_sha,
        )
    except Exception:  # noqa: BLE001 - an unread merge is simply unknown here
        return ""


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
    fetch_state: dict = {}
    batch = read_recorded_batch(item_id, pr_num=pr_num)
    # The merge the base actually holds this lane's work under. Resolved
    # before the receipt because both the receipt and the marker repoint
    # below ask about that merge rather than about the pull request the
    # item last armed, which a re-arm can move to one that never lands.
    landing_sha = _landing_merge(ctx, commit_sha, fetch_state)
    ci_evidence_error = ""
    ci_evidence_retryable = True
    ci_evidence_recovery = ""
    if batch is not None:
        # The proof is already where the terminal gate reads it. Recording it
        # again would only add a duplicate row, and re-deriving it could only
        # disagree with the item's own landing.
        merge_sha = batch.merge_sha
    else:
        batch, batch_failure = observe_batch(
            ctx,
            pr_num=pr_num,
            member_snapshot=member_snapshot,
            drift_check=drift_check,
            # Needed when the item's own pull request never merged:
            # that landing has a merge_group run only under the pull
            # request whose merge the base actually holds.
            landed_merge_sha=landing_sha,
        )
        if batch_failure is not None:
            warnings.append(batch_failure.reason)
            ci_evidence_retryable = batch_failure.retryable
            ci_evidence_recovery = batch_failure.recovery
        merge_sha = batch.merge_sha if batch is not None else ""
        if batch is None:
            ci_evidence_error = (
                batch_failure.reason
                if batch_failure is not None
                else f"merge-group CI receipt for pull request {pr_num} was "
                "not resolved"
            )
        elif not batch.head_sha or not batch.run_url:
            ci_evidence_error = (
                batch_failure.reason
                if batch_failure is not None
                else f"merge-group CI receipt for pull request {pr_num} "
                "omitted its verified head or run URL"
            )
        else:
            evidence_error = record_batch_evidence(item_id, batch)
            if evidence_error:
                ci_evidence_error = evidence_error
                ci_evidence_retryable = True
                ci_evidence_recovery = ""
                warnings.append(f"batch evidence not recorded: {evidence_error}")

    # Repointed before the stamp, because every landing fact belongs to one
    # pull request: a marker naming a pull request that never merged would
    # otherwise date this landing from its predecessor's stamps and send the
    # next close-out back to the same open pull request.
    repoint_note = repoint_to_landing_carrier(
        ctx,
        item_id=item_id,
        recorded_pr_number=pr_num,
        merge_sha=landing_sha,
    )
    if repoint_note:
        warnings.append(repoint_note)

    # Stamped here rather than on entry, because the landing's own merge
    # commit is what dates it and that is only known now. Stamping first
    # recorded the moment close-out ran, which for a re-entered close-out is
    # hours after the merge and for an item landing a second time is a date
    # belonging to the landing it just replaced.
    stamp_error = stamp_merged_at(
        item_id, repo_root=ctx.repo_root or "", merge_sha=merge_sha
    )
    if stamp_error:
        warnings.append(f"merged_at not recorded: {stamp_error}")

    touched, files_error = read_pr_changed_files(ctx, pr_num)
    if files_error:
        warnings.append(f"touched files not resolved: {files_error}")
    elif not touched:
        warnings.append(
            f"pull request {pr_num} reports no changed files"
        )
    touched_files = tuple(touched or ())
    if not touched_files and ctx.repo_root and commit_sha:
        touched_files = _files_from_merge_commit(ctx, commit_sha, fetch_state)
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
        ci_evidence_retryable=ci_evidence_retryable,
        ci_evidence_recovery=ci_evidence_recovery,
        warnings=tuple(warnings),
    )


__all__ = ["QueueCloseOut", "record_landing"]
