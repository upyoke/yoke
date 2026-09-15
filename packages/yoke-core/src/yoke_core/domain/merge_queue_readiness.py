"""Read one landing's queue standing without mutating it.

GitHub consumes ``autoMergeRequest`` when a merge-queue entry forms.  A
null arming field therefore has two opposite meanings: the queue may be
driving the pull request, or nothing may be driving it.  This read composes
the pull-request state with ``mergeQueue(branch).entries`` and names the
entry state so callers never infer liveness from the arming field alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from yoke_core.domain.merge_queue_entry_checks import (
    ENTRY_CHECKS_FAILED,
    describe_failed_checks,
    failed_required_checks,
)
from yoke_core.domain.merge_queue_readback_outcomes import (
    ARMED_NOT_ENQUEUED,
    CLOSED_UNMERGED,
    CONFLICTED,
    ENQUEUED,
    ENTRY_ABSENT,
    ENTRY_NOT_READ,
    ENTRY_PRESENT,
    IN_FLIGHT,
    LANDED,
    MERGE_WHEN_READY_ARMED,
    MERGE_WHEN_READY_CLEARED,
    MERGE_WHEN_READY_CONSUMED,
    NEITHER,
    NOT_IN_FLIGHT,
    NOT_STARTED,
    UNREADABLE,
)
from yoke_core.engines.merge_worktree_pr_check_runs import (
    LandingCheck,
    check_payload,
    read_required_checks,
)
from yoke_core.engines.merge_worktree_pr_queue import (
    PrLandingState,
    QueueMember,
    read_pr_landing_state,
    read_queue_members,
)
from yoke_core.engines.merge_worktree_prepare import MergeContext


@dataclass(frozen=True)
class MergeQueueReadiness:
    """The named facts that answer whether one landing is still moving."""

    pr_number: str
    target: str
    landing_state: str
    in_flight: Optional[bool]
    queue_holding: str
    queue_entry_state: str
    merge_when_ready: str
    merged: Optional[bool] = None
    closed: Optional[bool] = None
    merge_state_status: str = ""
    #: The commit the pull request's head branch points at on origin.
    head_sha: str = ""
    #: The commit GitHub recorded for a merged pull request, and when. A
    #: caller that finds a candidate already landed reports the head that
    #: actually landed rather than the one it was holding.
    merge_commit_sha: str = ""
    merged_at: str = ""
    failed_checks: tuple[LandingCheck, ...] = field(default=())
    warnings: tuple[str, ...] = field(default=())

    @property
    def needs_action(self) -> bool:
        """Whether this read found no live landing to wait for."""
        return self.landing_state not in (IN_FLIGHT, LANDED, NOT_STARTED)

    @property
    def queue_readable(self) -> bool:
        """Whether the target branch's queue answered at all."""
        return self.queue_entry_state not in (ENTRY_NOT_READ, UNREADABLE)

    @property
    def has_queue_entry(self) -> bool:
        """Whether GitHub reports this pull request holding a queue entry."""
        return self.queue_readable and self.queue_entry_state != ENTRY_ABSENT

    @property
    def armed(self) -> bool:
        """Whether merge-when-ready is set and not yet consumed by an entry."""
        return self.merge_when_ready == MERGE_WHEN_READY_ARMED

    @property
    def queue_clear(self) -> bool:
        """Whether neither an entry nor a live arming is driving the landing.

        Both halves are read facts, and both are needed: ``merge_when_ready``
        reports ``cleared`` only when the pull request carries no arming AND
        no entry consumed one, so the pair together is what distinguishes a
        held candidate from one the queue is still driving.
        """
        return (
            self.queue_readable
            and self.queue_entry_state == ENTRY_ABSENT
            and self.merge_when_ready == MERGE_WHEN_READY_CLEARED
        )

    def describe(self) -> str:
        """Render the facts without treating a consumed arming as cleared."""
        return (
            f"pull request {self.pr_number or 'not recorded'}: "
            f"landing={self.landing_state}, queue-holding={self.queue_holding}, "
            f"queue-entry={self.queue_entry_state}, "
            f"merge-when-ready={self.merge_when_ready}, "
            f"merged={_truth(self.merged)}, "
            f"state={_open_state(self.closed)}, "
            f"mergeStateStatus={self.merge_state_status or 'unreported'}, "
            f"failed-required-checks={describe_failed_checks(self.failed_checks)}"
        )

    def to_dict(self) -> dict[str, object]:
        """Return the transport-safe projection shared by public readers."""
        return {
            "pr_number": self.pr_number,
            "target": self.target,
            "landing_state": self.landing_state,
            "in_flight": self.in_flight,
            "queue_holding": self.queue_holding,
            "queue_entry_state": self.queue_entry_state,
            "merge_when_ready": self.merge_when_ready,
            "merged": self.merged,
            "closed": self.closed,
            "merge_state_status": self.merge_state_status,
            "head_sha": self.head_sha,
            "merge_commit_sha": self.merge_commit_sha,
            "merged_at": self.merged_at,
            "failed_checks": [check_payload(check) for check in self.failed_checks],
            "narrative": self.describe(),
            "warnings": list(self.warnings),
        }


def _truth(value: Optional[bool]) -> str:
    if value is None:
        return UNREADABLE
    return "true" if value else "false"


def _open_state(closed: Optional[bool]) -> str:
    if closed is None:
        return UNREADABLE
    return "closed" if closed else "open"


def _entry_for(members: Sequence[QueueMember], pr_number: str) -> Optional[QueueMember]:
    return next((row for row in members if row.pr_num == pr_number), None)


def classify_readiness(
    *,
    pr_number: str,
    target: str,
    state: Optional[PrLandingState],
    members: Optional[Sequence[QueueMember]],
    state_error: str = "",
    queue_error: str = "",
    required_checks: Optional[Sequence[LandingCheck]] = None,
    checks_error: str = "",
) -> MergeQueueReadiness:
    """Compose independently read PR, branch-queue, and required-check facts.

    Required checks are the same terminal fact the landing notifier already
    classifies (:mod:`yoke_core.domain.merge_queue_entry_checks`): GitHub
    creates the queue entry only once a pull request's own required checks
    pass, so one that has already concluded red while still merely armed —
    ``queue_holding=armed_not_enqueued`` — is a landing that cannot happen,
    not an ordinary wait. Reading only the arming field reported that state
    as a healthy ``in_flight`` and left the notifier as the only place that
    ever noticed.
    """
    warnings = tuple(note for note in (state_error, queue_error, checks_error) if note)
    entry = _entry_for(members or (), pr_number) if members is not None else None
    failed_checks = failed_required_checks(required_checks)
    entry_state = (
        (entry.state or ENTRY_PRESENT).strip().upper()
        if entry is not None
        else ENTRY_ABSENT
        if members is not None
        else UNREADABLE
    )

    if entry is not None:
        holding = ENQUEUED
    elif members is None or state is None:
        holding = UNREADABLE
    elif state.auto_merge_active:
        holding = ARMED_NOT_ENQUEUED
    else:
        holding = NEITHER

    if state is None:
        arming = UNREADABLE
    elif state.auto_merge_active:
        arming = MERGE_WHEN_READY_ARMED
    elif entry is not None:
        arming = MERGE_WHEN_READY_CONSUMED
    else:
        arming = MERGE_WHEN_READY_CLEARED

    if state is not None and state.merged:
        landing_state, in_flight = LANDED, False
    elif entry is not None:
        landing_state, in_flight = IN_FLIGHT, True
    elif state is not None and state.closed:
        landing_state, in_flight = CLOSED_UNMERGED, False
    elif state is not None and state.merge_state_status.strip().lower() == "dirty":
        landing_state, in_flight = CONFLICTED, False
    elif failed_checks:
        # Not in the queue and one of the PR's own required checks already
        # concluded red: GitHub will never create the entry, whatever the
        # arming field still reports.
        landing_state, in_flight = ENTRY_CHECKS_FAILED, False
    elif state is not None and state.auto_merge_active:
        landing_state, in_flight = IN_FLIGHT, True
    elif state is None or members is None:
        landing_state, in_flight = UNREADABLE, None
    else:
        landing_state, in_flight = NOT_IN_FLIGHT, False

    return MergeQueueReadiness(
        pr_number=pr_number,
        target=target,
        landing_state=landing_state,
        in_flight=in_flight,
        queue_holding=holding,
        queue_entry_state=entry_state,
        merge_when_ready=arming,
        merged=state.merged if state is not None else None,
        closed=state.closed if state is not None else None,
        merge_state_status=(state.merge_state_status or "").upper()
        if state is not None
        else "",
        head_sha=state.head_sha if state is not None else "",
        merge_commit_sha=state.merge_commit_sha if state is not None else "",
        merged_at=state.merged_at if state is not None else "",
        failed_checks=failed_checks,
        warnings=warnings,
    )


def read_merge_queue_readiness(
    ctx: MergeContext, *, pr_number: str, target: str
) -> MergeQueueReadiness:
    """Read the PR, the target branch's queue, and required checks.

    A merged pull request answers everything the required checks could —
    it already landed — so the read is skipped there; every other outcome
    needs the same terminal fact the landing notifier already reads.
    """
    state, state_error = read_pr_landing_state(ctx, pr_number)
    members, queue_error = read_queue_members(ctx, base_branch=target)
    required_checks: Optional[Sequence[LandingCheck]] = None
    checks_error = ""
    if state is not None and not state.merged:
        required_checks, checks_error = read_required_checks(ctx, pr_number)
    return classify_readiness(
        pr_number=pr_number,
        target=target,
        state=state,
        members=members,
        state_error=state_error or "",
        queue_error=queue_error or "",
        required_checks=required_checks,
        checks_error=checks_error or "",
    )


def not_started(*, target: str) -> MergeQueueReadiness:
    """The item has no recorded landing pull request to inspect."""
    return MergeQueueReadiness(
        pr_number="",
        target=target,
        landing_state=NOT_STARTED,
        in_flight=False,
        queue_holding=NOT_STARTED,
        queue_entry_state=ENTRY_NOT_READ,
        merge_when_ready=ENTRY_NOT_READ,
    )


__all__ = [
    "ARMED_NOT_ENQUEUED",
    "ENQUEUED",
    "ENTRY_ABSENT",
    "ENTRY_CHECKS_FAILED",
    "ENTRY_NOT_READ",
    "ENTRY_PRESENT",
    "IN_FLIGHT",
    "MERGE_WHEN_READY_ARMED",
    "MERGE_WHEN_READY_CLEARED",
    "MERGE_WHEN_READY_CONSUMED",
    "MergeQueueReadiness",
    "NEITHER",
    "NOT_IN_FLIGHT",
    "UNREADABLE",
    "classify_readiness",
    "not_started",
    "read_merge_queue_readiness",
]
