"""What one observation of a queued pull request actually means.

Merging and ejection look identical from a single read. GitHub clears
merge-when-ready when the queue merges a pull request and when it drops
it, and the merged flag becomes visible a moment later, so a poll in
that window sees an unmerged, unarmed pull request. Nothing here is
terminal on one read except red required checks: a check GitHub gates
the queue entry on that has already concluded
failed/error/cancelled/timed_out on the pull request's head. The rest of
the set still running does not soften that — the entry can never happen
— so it must not spend the poll budget. Other refusals still
confirm: merged is re-read after a short delay; a still-queued entry is
still landing; an unmerged, open, unarmed pull request the queue no
longer holds, with no identified train
still driving it, has stalled. Every verdict names the facts it saw,
including ``mergeStateStatus`` so ``DIRTY`` is not a silent wait.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from yoke_core.domain.github_poll_schedule import (
    MINIMUM_POLL_INTERVAL_SECONDS,
)
from yoke_core.engines.merge_worktree_pr_queue import (
    PrLandingState,
    QueueMember,
    TrainRun,
    read_pr_landing_state,
    read_queue_members,
    read_train_run,
)
from yoke_core.engines.merge_worktree_prepare import MergeContext
from yoke_core.domain.merge_queue_entry_checks import (
    ENTRY_CHECKS_FAILED,
    failed_required_checks,
)
from yoke_core.engines.merge_worktree_pr_check_runs import (
    LandingCheck,
    read_landing_checks,
    read_required_checks,
)

# Queue ejection is a failed train, not an empty slot. GitHub clears the
# slot and merge-when-ready while a successful train is still merging.
_FAILED_TRAIN_CONCLUSIONS = frozenset(
    {"cancelled", "failure", "startup_failure", "timed_out"}
)


# What the pull request turned out to be doing.
LANDED = "landed"
CLOSED_UNMERGED = "closed_unmerged"
CONFLICTED = "conflicted"
STALLED = "stalled"
PENDING = "pending"

DEFAULT_CONFIRM_SECONDS = MINIMUM_POLL_INTERVAL_SECONDS


@dataclass(frozen=True)
class LandingVerdict:
    """One classification of a queued pull request, with what it observed."""

    kind: str
    narrative: str = ""
    warnings: tuple[str, ...] = field(default=())
    head_sha: str = ""
    failed_checks: tuple[LandingCheck, ...] = field(default=())


def describe_checks(checks: Sequence[LandingCheck]) -> str:
    """Pending and concluded check names, sorted so a reshuffle is not news."""
    pending = sorted(check.name for check in checks if check.status != "completed")
    concluded = sorted(
        f"{check.name}={check.conclusion or check.status}"
        for check in checks
        if check.status == "completed"
    )
    return (
        f"pending-checks={','.join(pending) or 'none'} "
        f"concluded-checks={','.join(concluded) or 'none'}"
    )


def describe(
    pr_num: str,
    state: PrLandingState,
    entry: Optional[QueueMember],
    entry_readable: bool,
    train: Optional[TrainRun],
    checks: Optional[tuple[LandingCheck, ...]] = None,
) -> str:
    """The observed facts behind a verdict, as plain named readings."""
    if not entry_readable:
        slot = "unreadable"
    elif entry is None:
        slot = "absent"
    else:
        slot = entry.state or "present"
    if train is None:
        # Unidentified, not absent: the reader answers ``None`` both when the
        # lookup failed and when no queue ref carried this pull request's
        # marker, and naming either as a concluded run is the substitution
        # that put an unrelated train's green in an ejection report.
        run = "not identified"
    else:
        run = train.conclusion or train.status or "unreported"
        if train.url:
            run = f"{run} ({train.url})"
    merge_state = (state.merge_state_status or "").strip().upper() or "unreported"
    arming = (
        "armed"
        if state.auto_merge_active
        else ("consumed" if entry_readable and entry is not None else "cleared")
    )
    narrative = (
        f"pull request {pr_num}: merged=false, "
        f"state={'closed' if state.closed else 'open'}, "
        f"merge-when-ready={arming}, "
        f"mergeStateStatus={merge_state}, "
        f"queue-entry={slot}, train-run={run}"
    )
    if checks is not None:
        narrative = f"{narrative}, {describe_checks(checks)}"
    return narrative


_Observe = tuple[
    str,
    Optional[QueueMember],
    bool,
    Optional[TrainRun],
    tuple[LandingCheck, ...],
]


def _observe(
    ctx: MergeContext,
    pr_num: str,
    state: PrLandingState,
    target: str,
    warnings: list[str],
) -> _Observe:
    """Read the slot, train, and checks behind ``state`` and describe them.

    Which check set answers depends on the phase. Once a train is
    building, the commit under validation is the train's and nothing on
    it is required for the pull request. Before that, the gate is the
    pull request's own required checks, and one of those already red is
    what makes the wait terminal rather than ordinary.
    """
    entry, entry_error = _queue_entry(ctx, pr_num, target)
    if entry_error:
        warnings.append(entry_error)
    train, train_note = read_train_run(ctx, pr_num)
    if train_note:
        warnings.append(train_note)
    failed: tuple[LandingCheck, ...] = ()
    if train is not None:
        checks, check_error = read_landing_checks(ctx, train.head_sha)
    else:
        checks, check_error = read_required_checks(ctx, pr_num)
        failed = failed_required_checks(checks)
    if check_error:
        warnings.append(check_error)
        checks = None
    narrative = describe(
        pr_num,
        state,
        entry,
        entry_error is None,
        train,
        checks,
    )
    return narrative, entry, entry_error is None, train, failed


def _queue_entry(
    ctx: MergeContext, pr_num: str, target: str
) -> tuple[Optional[QueueMember], Optional[str]]:
    """The queue's entry for ``pr_num``, if the queue can be read at all."""
    members, error = read_queue_members(ctx, base_branch=target)
    if error or members is None:
        return None, error or "queue membership unreadable"
    for member in members:
        if member.pr_num == str(pr_num):
            return member, None
    return None, None


def _has_conflicts(state: PrLandingState) -> bool:
    """GitHub ``DIRTY``: the merge commit cannot be created."""
    return state.merge_state_status.strip().lower() == "dirty"


def _train_still_working(train: Optional[TrainRun]) -> bool:
    """A train that was identified and has not failed is still driving.

    An *unidentified* train is not evidence of work in progress. Reading it
    as such is how an ejected pull request — dropped before any train ever
    carried it, so no queue ref bears its marker — stayed PENDING until the
    poll budget ran out and the wait reported a timeout instead of the
    ejection it had been observing all along.
    """
    if train is None:
        return False
    return (train.conclusion or "").strip().lower() not in _FAILED_TRAIN_CONCLUSIONS


def classify_landing(
    ctx: MergeContext,
    *,
    pr_num: str,
    target: str,
    sleep: Callable[[float], None],
    confirm_seconds: float = DEFAULT_CONFIRM_SECONDS,
) -> LandingVerdict:
    """Decide what the pull request is doing, confirming before any refusal."""
    warnings: list[str] = []
    state, error = read_pr_landing_state(ctx, pr_num)
    if error:
        warnings.append(error)
    if state is None:
        return LandingVerdict(
            PENDING,
            narrative=f"pull request {pr_num}: unreadable this observation",
            warnings=tuple(warnings),
        )
    if state.merged:
        return LandingVerdict(
            LANDED,
            narrative=f"pull request {pr_num}: merged=true",
            warnings=tuple(warnings),
        )
    if state.auto_merge_active and not state.closed and not _has_conflicts(state):
        narrative, _entry, _readable, train, failed = _observe(
            ctx, pr_num, state, target, warnings
        )
        if failed:
            return LandingVerdict(
                ENTRY_CHECKS_FAILED,
                narrative=narrative,
                warnings=tuple(warnings),
                head_sha=state.head_sha,
                failed_checks=failed,
            )
        return LandingVerdict(PENDING, narrative=narrative, warnings=tuple(warnings))

    # Unmerged and either closed, unarmed, or conflicted. A merge in
    # flight can look the same, so the reading is confirmed first.
    sleep(confirm_seconds)
    confirmed, confirm_error = read_pr_landing_state(ctx, pr_num)
    if confirm_error:
        warnings.append(confirm_error)
    if confirmed is None:
        return LandingVerdict(
            PENDING,
            narrative=f"pull request {pr_num}: unreadable this observation",
            warnings=tuple(warnings),
        )
    if confirmed.merged:
        return LandingVerdict(
            LANDED,
            narrative=f"pull request {pr_num}: merged=true",
            warnings=tuple(warnings),
        )

    narrative, entry, entry_readable, train, failed = _observe(
        ctx, pr_num, confirmed, target, warnings
    )
    if failed:
        return LandingVerdict(
            ENTRY_CHECKS_FAILED,
            narrative=narrative,
            warnings=tuple(warnings),
            head_sha=confirmed.head_sha,
            failed_checks=failed,
        )
    if _has_conflicts(confirmed) and not confirmed.closed:
        return LandingVerdict(CONFLICTED, narrative=narrative, warnings=tuple(warnings))
    if not confirmed.closed:
        # An unreadable queue cannot prove the entry is gone. An entry that
        # is still there, arming still set, or an identified train that has
        # not failed all mean GitHub is still working — the slot and arming
        # clear before merged=true.
        still_landing = (
            not entry_readable
            or entry is not None
            or confirmed.auto_merge_active
            or _train_still_working(train)
        )
        if still_landing:
            return LandingVerdict(
                PENDING, narrative=narrative, warnings=tuple(warnings)
            )
    return LandingVerdict(
        CLOSED_UNMERGED if confirmed.closed else STALLED,
        narrative=narrative,
        warnings=tuple(warnings),
    )


__all__ = [
    "CLOSED_UNMERGED",
    "CONFLICTED",
    "DEFAULT_CONFIRM_SECONDS",
    "ENTRY_CHECKS_FAILED",
    "LANDED",
    "LandingCheck",
    "LandingVerdict",
    "PENDING",
    "STALLED",
    "classify_landing",
    "describe",
    "describe_checks",
    "read_landing_checks",
    "read_required_checks",
]
