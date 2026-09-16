"""Hold one merge-queue candidate: clear its arming, remove its entry, verify.

Disarming and dequeuing are two different mutations against two different
states. GitHub consumes ``autoMergeRequest`` when it forms the queue entry,
so disabling merge-when-ready on an already-consumed candidate changes
nothing the queue is acting on — the entry keeps its place and can still
merge the head it holds. A holder correcting a defective candidate needs
both cleared, and needs that read back: reporting a hold that did not take
is what lets a correction push race the landing it thought it had stopped.

The hold therefore acts, re-reads
(:mod:`yoke_core.domain.merge_queue_readiness`), and acts once more on what
that read shows, which is what covers the consumption race — a candidate
merely armed when the first read ran, and holding an entry by the time the
disarm returned. It never reports held without a readback that shows the
entry absent and the arming cleared, and a candidate that landed before or
during the hold is reported as landed with the merge commit GitHub actually
recorded rather than as a failed hold.

Re-arming is a separate, explicit act: correct the lane, re-run the
verification gate against the exact new candidate, and re-run
``yoke merge item``. Nothing here re-arms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from yoke_core.domain.merge_queue_readback_outcomes import (
    HOLD_ALREADY_CLEAR,
    HOLD_ALREADY_LANDED,
    HOLD_HELD,
    HOLD_LANDED_DURING_HOLD,
    HOLD_NOT_HELD,
    HOLD_UNVERIFIED,
    HOLD_USER_AUTHORITY_REQUIRED,
)
from yoke_core.domain.project_github_auth_tokens import (
    bound_local_github_user_token_provider,
)
from yoke_core.domain.merge_queue_readiness import (
    MergeQueueReadiness,
    read_merge_queue_readiness,
)
from yoke_core.engines.merge_worktree_pr_queue import (
    QueueEntryResult,
    dequeue_pull_request,
    leave_merge_queue,
)
from yoke_core.engines.merge_worktree_pr_rest import GITHUB_AUTHORITY_USER
from yoke_core.engines.merge_worktree_prepare import MergeContext

#: Act, read back, act once more on what the readback showed. A third pass
#: would be chasing a queue that is moving faster than the hold can read it,
#: which is a refusal to report rather than a loop to widen.
_MAX_PASSES = 2

#: Why a hold can refuse before touching GitHub, and where it can succeed.
#: Holding a live candidate is an operator act, so this requires the
#: operator's bound GitHub authorization rather than falling back to the
#: installation. A relayed hold runs where no such authorization exists
#: and says so instead of substituting the App, whose attempt was observed
#: refused with nothing named.
USER_AUTHORITY_RECOVERY = (
    "holding a live candidate requires bound operator GitHub "
    "authorization, and this process has none; run `yoke github "
    "merge-queue hold` from the machine that holds it"
)

#: What a holder does next, once the candidate is actually held.
REARM_RECOVERY = (
    "correct the lane, commit, re-run the verification gate against the new "
    "candidate, and re-run `yoke merge item` to re-arm it"
)


@dataclass(frozen=True)
class LandingHold:
    """What a hold attempt did and what GitHub reported afterwards."""

    outcome: str
    held: bool
    pr_number: str
    target: str
    #: Each mutation attempted, in order, with what it answered.
    actions: tuple[str, ...] = field(default=())
    before: Optional[MergeQueueReadiness] = None
    after: Optional[MergeQueueReadiness] = None
    merged: bool = False
    merge_commit_sha: str = ""
    merged_at: str = ""
    refusal: str = ""

    def describe(self) -> str:
        """One line naming the outcome, the readback, and what is next."""
        observed = self.after or self.before
        readback = observed.describe() if observed is not None else "unread"
        tail = f" {self.refusal}" if self.refusal else f" Next: {REARM_RECOVERY}."
        return (
            f"hold {self.outcome}: pull request "
            f"{self.pr_number or 'not recorded'} on {self.target}. "
            f"Observed {readback}.{tail}"
        )

    def to_dict(self) -> dict[str, object]:
        """The transport-safe projection the registered function returns."""
        return {
            "outcome": self.outcome,
            "held": self.held,
            "pr_number": self.pr_number,
            "target": self.target,
            "actions": list(self.actions),
            "before": self.before.to_dict() if self.before is not None else None,
            "after": self.after.to_dict() if self.after is not None else None,
            "merged": self.merged,
            "merge_commit_sha": self.merge_commit_sha,
            "merged_at": self.merged_at,
            "refusal": self.refusal,
            "narrative": self.describe(),
        }


def _note(label: str, result: QueueEntryResult) -> str:
    if result.success:
        return f"{label}: ok"
    return f"{label}: refused ({(result.error_detail or 'no detail').strip()})"


def _act(ctx: MergeContext, readiness: MergeQueueReadiness) -> tuple[str, ...]:
    """Run the mutations the readback says are still needed."""
    notes: list[str] = []
    # The hold boundary has already proven operator authorization is
    # bound, so these name it rather than inheriting the installation
    # default the landing observer relies on.
    if readiness.armed:
        notes.append(
            _note(
                "disarm merge-when-ready",
                leave_merge_queue(
                    ctx,
                    readiness.pr_number,
                    required_authority=GITHUB_AUTHORITY_USER,
                ),
            )
        )
    if readiness.has_queue_entry:
        notes.append(
            _note(
                "dequeue entry",
                dequeue_pull_request(
                    ctx,
                    readiness.pr_number,
                    required_authority=GITHUB_AUTHORITY_USER,
                ),
            )
        )
    return tuple(notes)


def _landed(
    readiness: MergeQueueReadiness,
    *,
    outcome: str,
    actions: tuple[str, ...],
    before: MergeQueueReadiness,
) -> LandingHold:
    """A candidate that merged is reported with the head GitHub recorded."""
    return LandingHold(
        outcome=outcome,
        held=False,
        pr_number=readiness.pr_number,
        target=readiness.target,
        actions=actions,
        before=before,
        after=readiness if readiness is not before else None,
        merged=True,
        merge_commit_sha=readiness.merge_commit_sha,
        merged_at=readiness.merged_at,
        refusal=(
            f"pull request {readiness.pr_number} already merged as "
            f"{readiness.merge_commit_sha or 'an unreported commit'}"
            f"{f' at {readiness.merged_at}' if readiness.merged_at else ''}; "
            "there is no candidate left to hold. That landing is the fact to "
            "carry forward — continue through the item's own lifecycle from "
            "here rather than treating the merge as an error."
        ),
    )


def hold_landing(ctx: MergeContext, *, pr_number: str, target: str) -> LandingHold:
    """Clear ``pr_number``'s arming and queue entry, and verify both cleared."""
    before = read_merge_queue_readiness(ctx, pr_number=pr_number, target=target)
    if before.merged:
        return _landed(before, outcome=HOLD_ALREADY_LANDED, actions=(), before=before)
    if before.queue_clear:
        return LandingHold(
            outcome=HOLD_ALREADY_CLEAR,
            held=True,
            pr_number=pr_number,
            target=target,
            before=before,
            after=before,
        )

    # Checked after the readback so a candidate that already landed or is
    # already clear still reports that, and before any mutation so a
    # process without bound operator authorization changes nothing.
    if bound_local_github_user_token_provider() is None:
        return LandingHold(
            outcome=HOLD_USER_AUTHORITY_REQUIRED,
            held=False,
            pr_number=pr_number,
            target=target,
            before=before,
            after=before,
            refusal=USER_AUTHORITY_RECOVERY,
        )

    actions: list[str] = []
    observed = before
    for _pass in range(_MAX_PASSES):
        actions.extend(_act(ctx, observed))
        observed = read_merge_queue_readiness(ctx, pr_number=pr_number, target=target)
        if observed.merged:
            return _landed(
                observed,
                outcome=HOLD_LANDED_DURING_HOLD,
                actions=tuple(actions),
                before=before,
            )
        if observed.queue_clear:
            return LandingHold(
                outcome=HOLD_HELD,
                held=True,
                pr_number=pr_number,
                target=target,
                actions=tuple(actions),
                before=before,
                after=observed,
            )
        if not observed.queue_readable:
            break

    if not observed.queue_readable:
        refusal = (
            "the queue could not be read back, so this hold is unverified: "
            f"{'; '.join(observed.warnings) or 'no detail reported'}. Do not "
            "push a correction until `yoke github merge-queue readiness` "
            "reports queue-entry=absent and merge-when-ready=cleared."
        )
        outcome = HOLD_UNVERIFIED
    else:
        refusal = (
            f"GitHub still reports queue-entry={observed.queue_entry_state} and "
            f"merge-when-ready={observed.merge_when_ready} after "
            f"{'; '.join(actions) or 'no mutation'}. The candidate is still "
            "live: do not push a correction against it. Re-run this hold, or "
            "let the landing finish and correct the result."
        )
        outcome = HOLD_NOT_HELD
    return LandingHold(
        outcome=outcome,
        held=False,
        pr_number=pr_number,
        target=target,
        actions=tuple(actions),
        before=before,
        after=observed,
        refusal=refusal,
    )


__all__ = ["LandingHold", "REARM_RECOVERY", "hold_landing"]
