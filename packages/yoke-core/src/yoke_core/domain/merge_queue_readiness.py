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

from yoke_core.engines.merge_worktree_pr_queue import (
    PrLandingState,
    QueueMember,
    read_pr_landing_state,
    read_queue_members,
)
from yoke_core.engines.merge_worktree_prepare import MergeContext


ENQUEUED = "enqueued"
ARMED_NOT_ENQUEUED = "armed_not_enqueued"
NEITHER = "neither"
UNREADABLE = "unreadable"
NOT_STARTED = "not_started"

IN_FLIGHT = "in_flight"
LANDED = "landed"
CLOSED_UNMERGED = "closed_unmerged"
CONFLICTED = "conflicted"
NOT_IN_FLIGHT = "not_in_flight"

ENTRY_ABSENT = "absent"
ENTRY_NOT_READ = "not_read"


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
    warnings: tuple[str, ...] = field(default=())

    @property
    def needs_action(self) -> bool:
        """Whether this read found no live landing to wait for."""
        return self.landing_state not in (IN_FLIGHT, LANDED, NOT_STARTED)

    def describe(self) -> str:
        """Render the facts without treating a consumed arming as cleared."""
        return (
            f"pull request {self.pr_number or 'not recorded'}: "
            f"landing={self.landing_state}, queue-holding={self.queue_holding}, "
            f"queue-entry={self.queue_entry_state}, "
            f"merge-when-ready={self.merge_when_ready}, "
            f"merged={_truth(self.merged)}, "
            f"state={_open_state(self.closed)}, "
            f"mergeStateStatus={self.merge_state_status or 'unreported'}"
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
) -> MergeQueueReadiness:
    """Compose independently read PR and branch-queue facts."""
    warnings = tuple(note for note in (state_error, queue_error) if note)
    entry = _entry_for(members or (), pr_number) if members is not None else None
    entry_state = (
        (entry.state or "present").strip().upper()
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
        arming = "armed"
    elif entry is not None:
        arming = "consumed"
    else:
        arming = "cleared"

    if state is not None and state.merged:
        landing_state, in_flight = LANDED, False
    elif entry is not None:
        landing_state, in_flight = IN_FLIGHT, True
    elif state is not None and state.closed:
        landing_state, in_flight = CLOSED_UNMERGED, False
    elif state is not None and state.merge_state_status.strip().lower() == "dirty":
        landing_state, in_flight = CONFLICTED, False
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
        warnings=warnings,
    )


def read_merge_queue_readiness(
    ctx: MergeContext, *, pr_number: str, target: str
) -> MergeQueueReadiness:
    """Read the PR and the target branch's queue, then compose their facts."""
    state, state_error = read_pr_landing_state(ctx, pr_number)
    members, queue_error = read_queue_members(ctx, base_branch=target)
    return classify_readiness(
        pr_number=pr_number,
        target=target,
        state=state,
        members=members,
        state_error=state_error or "",
        queue_error=queue_error or "",
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
    "IN_FLIGHT",
    "MergeQueueReadiness",
    "NEITHER",
    "NOT_IN_FLIGHT",
    "classify_readiness",
    "not_started",
    "read_merge_queue_readiness",
]
