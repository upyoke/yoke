"""What one queue-landed member records once its train lands.

The queue validates a whole train's combined head server-side, so a member's
close-out is bookkeeping rather than work: stamp when it landed, record the
shared verification receipt as covering evidence, and record the merge receipt
that names what this landing is answerable for — the candidate head the
landing record says the queue merged, that landing's merge commit, and the
files the branch changed. A cached lane head is not that candidate.

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
from typing import Callable, Mapping, Optional

from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain import item_merge_contributed_commits as contributed
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
from yoke_core.domain.engine_runtime_ports import get_main_checkout_sync
from yoke_core.domain.merge_github_files import read_pr_changed_files
from yoke_core.domain.merge_context import MergeContext

fast_forward_main_checkout = get_main_checkout_sync().fast_forward_main_checkout


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
    # The commit the receipt named. Empty when the receipt was refused.
    receipt_commit_sha: str = ""
    # Why the receipt was not written. Close-out retries this; it does not
    # fill the gap with a cached lane head.
    receipt_error: str = ""

    def ci_evidence_refusal(self, pr_num: str, resume_command: str = "") -> str:
        """Name the recovery for a landing whose proof was not recorded."""
        if self.receipt_error:
            return self.receipt_error
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
        ctx.repo_root,
        f"origin/{ctx.args.target}",
        commit_sha,
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

    Feed it the candidate being closed out, never an older commit the item
    also carries. Everything on the base has a merge that carried it, so an
    earlier candidate answers accurately for an earlier landing — and a
    correction relanded on the same lane would be pointed back at the
    landing it replaced. A queue batch's merge commit is the train's tip,
    not this member's own merge, so it never stands in for this answer.
    """
    if not ctx.repo_root or not commit_sha:
        return ""
    try:
        _fetch_once(ctx, state)
        return receipts.landing_merge_commit(
            ctx.repo_root,
            f"origin/{ctx.args.target}",
            commit_sha,
        )
    except Exception:  # noqa: BLE001 - an unread merge is simply unknown here
        return ""


def record_landing(
    ctx: MergeContext,
    *,
    item_id: int,
    commit_sha: str,
    pr_num: str,
    candidate_sha: str = "",
    member_snapshot: tuple[str, ...] = (),
    drift_check: Optional[Mapping[str, str]] = None,
    resolve_landed_head: Optional[Callable[[int], tuple[str, str]]] = None,
) -> QueueCloseOut:
    """Record the candidate's own landing and its train's verification."""
    from yoke_core.domain.merge_landing_proof import (
        LandingUnverified,
        verified_landing_identity,
        verified_target_sha,
    )

    receipt_commit = commit_sha
    receipt_error = ""
    if resolve_landed_head is not None:
        receipt_commit, gap = resolve_landed_head(item_id)
        if not receipt_commit:
            return QueueCloseOut(
                receipt_error=(
                    "merge receipt not recorded: "
                    + (gap or "the landing record named no candidate head")
                    + ". The cached lane head is not recorded in its place."
                )
            )
        candidate_sha = receipt_commit
    try:
        remote_sha = verified_target_sha(
            ctx.repo_root, ctx.args.target, candidate_sha or commit_sha
        )
    except LandingUnverified as exc:
        note = receipts.record_failure(
            item_id,
            branch=ctx.args.branch,
            target=ctx.args.target,
            label="merge_landing_unverified",
            phase="queue_close_out",
            reason=str(exc),
        )
        return QueueCloseOut(receipt_error=str(exc), warnings=(note,) if note else ())
    warnings: list[str] = []
    fetch_state: dict = {}
    batch = read_recorded_batch(item_id, pr_num=pr_num)
    landing_sha = _landing_merge(ctx, candidate_sha or commit_sha, fetch_state)
    ci_evidence_error = ""
    ci_evidence_retryable = True
    ci_evidence_recovery = ""
    if batch is None:
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
                ci_evidence_error = evidence_error.reason
                ci_evidence_retryable = evidence_error.retryable
                ci_evidence_recovery = evidence_error.recovery
                warnings.append(f"batch evidence not recorded: {evidence_error.reason}")

    try:
        landing_sha = verified_landing_identity(
            ctx.repo_root, remote_sha, candidate_sha or commit_sha, landing_sha
        )
    except LandingUnverified as exc:
        return QueueCloseOut(receipt_error=str(exc))
    repoint_note = repoint_to_landing_carrier(
        ctx,
        item_id=item_id,
        recorded_pr_number=pr_num,
        merge_sha=landing_sha,
    )
    if repoint_note:
        warnings.append(repoint_note)

    stamp_error = stamp_merged_at(
        item_id,
        repo_root=ctx.repo_root or "",
        merge_sha=landing_sha,
    )
    if stamp_error:
        warnings.append(f"merged_at not recorded: {stamp_error}")

    touched, files_error = read_pr_changed_files(ctx, pr_num)
    if files_error:
        warnings.append(f"touched files not resolved: {files_error}")
    elif not touched:
        warnings.append(f"pull request {pr_num} reports no changed files")
    touched_files = tuple(touched or ())
    if not touched_files and ctx.repo_root and commit_sha:
        touched_files = _files_from_merge_commit(ctx, commit_sha, fetch_state)
        if touched_files:
            warnings.append(
                f"touched files read from the merge that landed {commit_sha[:12]} "
                f"rather than from pull request {pr_num}"
            )

    if receipt_commit:
        receipt_note = receipts.record(
            item_id,
            receipts.MergeReceipt(
                branch=ctx.args.branch,
                target=ctx.args.target,
                commit_sha=receipt_commit,
                merge_sha=landing_sha,
                touched_files=touched_files,
                contributed_commits=contributed.after_landing(
                    ctx.repo_root or "",
                    commit_sha=receipt_commit,
                    merge_sha=landing_sha,
                ),
            ),
        )
        if receipt_note:
            warnings.append(receipt_note)

    if ctx.repo_root:
        sync_warning = fast_forward_main_checkout(ctx.repo_root, ctx.args.target)
        if sync_warning:
            warnings.append(sync_warning)
    return QueueCloseOut(
        merge_sha=landing_sha,
        touched_files=touched_files,
        batch=batch,
        ci_evidence_error=ci_evidence_error,
        ci_evidence_retryable=ci_evidence_retryable,
        ci_evidence_recovery=ci_evidence_recovery,
        warnings=tuple(warnings),
        receipt_commit_sha=receipt_commit,
        receipt_error=receipt_error,
    )


__all__ = ["QueueCloseOut", "record_landing"]
