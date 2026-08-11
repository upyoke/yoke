"""What one observation of a queued pull request actually means.

Merging and ejection look identical from a single read. GitHub clears
merge-when-ready when the queue merges a pull request and when the queue
drops it, and the merged flag becomes visible a moment later, so a poll that
lands in that window sees an unmerged, unarmed pull request and calls a
successful landing a failure. Every misread of the kind came from deciding
on one read.

So nothing here is terminal on one read:

* the merged flag is confirmed with a second read taken after a short delay,
  because merging is the outcome that outranks every other reading;
* a pull request that is still a queue entry is still landing however its
  arming flag reads, since the queue clears arming while a train validates;
* only a pull request that is unmerged, open, unarmed, and absent from the
  queue after that confirmation has genuinely stopped.

A terminal verdict names every fact it saw, including what the train's own
``merge_group`` run concluded — asserting failed train checks without
reading them is what sent an operator to inspect a green run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from yoke_core.engines.merge_worktree_pr_queue import (
    PrLandingState,
    QueueMember,
    TrainRun,
    read_pr_landing_state,
    read_queue_members,
    read_train_run,
)
from yoke_core.engines.merge_worktree_prepare import MergeContext


# What the pull request turned out to be doing.
LANDED = "landed"
CLOSED_UNMERGED = "closed_unmerged"
STALLED = "stalled"
PENDING = "pending"

# How long to wait before the read that separates a merge in flight from a
# pull request the queue has stopped driving. Short enough to keep a genuine
# refusal prompt, long enough to outlast the merge's own read window.
DEFAULT_CONFIRM_SECONDS = 15.0


@dataclass(frozen=True)
class LandingVerdict:
    """One classification of a queued pull request, with what it observed."""

    kind: str
    narrative: str = ""
    warnings: tuple[str, ...] = field(default=())


def describe(
    pr_num: str,
    state: PrLandingState,
    entry: Optional[QueueMember],
    entry_readable: bool,
    train: Optional[TrainRun],
) -> str:
    """The observed facts behind a verdict, as plain named readings."""
    if not entry_readable:
        slot = "unreadable"
    elif entry is None:
        slot = "absent"
    else:
        slot = entry.state or "present"
    if train is None:
        run = "not found"
    else:
        run = train.conclusion or train.status or "unreported"
        if train.url:
            run = f"{run} ({train.url})"
    return (
        f"pull request {pr_num}: merged=false, "
        f"state={'closed' if state.closed else 'open'}, "
        f"merge-when-ready={'armed' if state.auto_merge_active else 'cleared'}, "
        f"queue-entry={slot}, train-run={run}"
    )


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
        return LandingVerdict(PENDING, warnings=tuple(warnings))
    if state.merged:
        return LandingVerdict(LANDED, warnings=tuple(warnings))
    if state.auto_merge_active and not state.closed:
        return LandingVerdict(PENDING, warnings=tuple(warnings))

    # Unmerged and either closed or unarmed. Both are also what a merge in
    # flight looks like, so the reading is confirmed before it is believed.
    sleep(confirm_seconds)
    confirmed, confirm_error = read_pr_landing_state(ctx, pr_num)
    if confirm_error:
        warnings.append(confirm_error)
    if confirmed is None:
        return LandingVerdict(PENDING, warnings=tuple(warnings))
    if confirmed.merged:
        return LandingVerdict(LANDED, warnings=tuple(warnings))

    entry, entry_error = _queue_entry(ctx, pr_num, target)
    if entry_error:
        warnings.append(entry_error)
    if not confirmed.closed:
        # An unreadable queue cannot prove the entry is gone, and an entry
        # that is still there means the train is still working on it.
        if entry_error or entry is not None or confirmed.auto_merge_active:
            return LandingVerdict(PENDING, warnings=tuple(warnings))
    train, train_note = read_train_run(ctx, pr_num)
    if train_note:
        warnings.append(train_note)
    return LandingVerdict(
        CLOSED_UNMERGED if confirmed.closed else STALLED,
        narrative=describe(
            pr_num, confirmed, entry, entry_error is None, train
        ),
        warnings=tuple(warnings),
    )


__all__ = [
    "CLOSED_UNMERGED",
    "DEFAULT_CONFIRM_SECONDS",
    "LANDED",
    "LandingVerdict",
    "PENDING",
    "STALLED",
    "classify_landing",
    "describe",
]
