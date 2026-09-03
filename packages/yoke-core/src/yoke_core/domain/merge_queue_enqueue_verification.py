"""Prove GitHub took the landing before reporting the handoff.

Three facts describe a pull request the queue is going to land, and a
landing that reads any one of them alone gets a different question
answered than the one it asked:

* **armed** — ``autoMergeRequest`` is set, so the merge-when-ready
  mutation actually took. This is the fact the handoff marker depends on,
  and the mutation returning success is not it: what the marker promises
  its holder is that GitHub is going to land the pull request, which only
  GitHub's own answer can establish.
* **queued** — ``isInMergeQueue`` / ``mergeQueueEntry``. GitHub creates
  the entry only once the pull request's own required checks pass, so an
  armed pull request whose checks are still running is legitimately not
  queued. Requiring this at arming time would refuse ordinary landings.
* **eligible** — ``mergeable`` / ``mergeStateStatus``. A pull request
  that has gone ``DIRTY`` cannot be taken, whatever the other two say.

So admission is a queue entry, or else armed *and* still eligible, and a
refusal names which of the three failed. The read-back is confirmed once
before refusing: arming has just been asked for rather than being a run
in progress, so it settles in seconds and the confirm is a bounded probe.
"""

from __future__ import annotations

from typing import Callable, Optional

from yoke_core.engines.merge_worktree_pr_membership import (
    PrQueueMembership,
    read_pr_queue_membership,
)
from yoke_core.engines.merge_worktree_pr_queue import (
    PrLandingState,
    read_pr_landing_state,
)
from yoke_core.engines.merge_worktree_prepare import MergeContext


#: How long to wait before re-reading an admission GitHub has not yet
#: reported. Arming moves within seconds, so this is a probe rather than
#: a poll: exactly one re-read, then a verdict.
ADMISSION_CONFIRM_SECONDS = 10.0

#: What each ``mergeable_state`` means for a pull request the queue is not
#: going to take, and what the holder has to do about it.
_ABSENCE_REASONS = {
    "dirty": (
        "it conflicts with its base branch — rebase the lane onto "
        "{target}, re-run the verification gate, and re-run `yoke merge item`"
    ),
    "behind": (
        "it is behind its base branch and the queue will not take it — "
        "rebase the lane onto {target} and re-run `yoke merge item`"
    ),
    "blocked": (
        "a required check, review, or protection rule is not satisfied — "
        "satisfy it and re-run `yoke merge item`"
    ),
    "draft": (
        "it is still a draft — mark it ready for review and re-run `yoke merge item`"
    ),
}

_DEFAULT_ABSENCE_REASON = (
    "GitHub reports it neither armed nor queued, with nothing in flight for "
    "it — address what the observation names and re-run `yoke merge item`"
)


def landing_eligible(state: Optional[PrLandingState]) -> bool:
    """False once GitHub cannot create this pull request's merge commit."""
    if state is None:
        return False
    if state.closed:
        return False
    return (state.merge_state_status or "").strip().lower() != "dirty"


def landing_admitted(
    state: Optional[PrLandingState],
    membership: Optional[PrQueueMembership],
) -> bool:
    """True when GitHub is holding this landing.

    A queue entry settles it on its own: whatever the other fields report,
    the queue is driving a pull request it still holds, and GitHub removes
    an entry it can no longer merge. Without an entry the landing has to be
    both armed and still eligible, which is the ordinary armed-and-waiting
    state before the pull request's own checks pass.

    ``None`` for either read is not an admission — an unreadable pull
    request proves nothing — but it is not a refusal either; callers
    distinguish the two.
    """
    if state is None or membership is None:
        return False
    if membership.in_queue:
        return True
    return state.auto_merge_active and landing_eligible(state)


def absence_reason(
    membership: Optional[PrQueueMembership],
    state: Optional[PrLandingState],
    *,
    target: str,
) -> str:
    """Why GitHub is not going to land this pull request, and the recovery."""
    if state is not None and state.closed:
        return "it is closed — reopen or recreate it and re-run `yoke merge item`"
    merge_state = (state.merge_state_status if state is not None else "").strip()
    if membership is not None and membership.mergeable == "CONFLICTING":
        merge_state = merge_state or "dirty"
    template = _ABSENCE_REASONS.get(merge_state.lower(), _DEFAULT_ABSENCE_REASON)
    return template.format(target=target)


def describe_admission(
    membership: Optional[PrQueueMembership],
    membership_error: Optional[str],
    state: Optional[PrLandingState],
) -> str:
    """The three fields behind an admission decision, as named readings."""
    if membership is not None:
        queue = membership.describe()
    else:
        queue = f"queue membership unreadable ({membership_error or 'no reason given'})"
    merge_state = (
        state.merge_state_status if state is not None else ""
    ) or "unreported"
    armed = (
        "armed"
        if state is not None and state.auto_merge_active
        else "cleared"
        if state is not None
        else "unreported"
    )
    return f"merge-when-ready={armed}, {queue}, mergeStateStatus={merge_state.upper()}"


def verify_landing_admitted(
    ctx: MergeContext,
    pr_num: str,
    *,
    target: str = "main",
    sleep: Callable[[float], None],
    confirm_seconds: float = ADMISSION_CONFIRM_SECONDS,
    read_membership: Callable[..., object] = read_pr_queue_membership,
    read_state: Callable[..., object] = read_pr_landing_state,
) -> str:
    """Return ``""`` once GitHub reports it is holding the landing for ``pr_num``.

    Any other outcome — an admission GitHub never made, or reads that
    cannot answer — returns a refusal naming all three fields and the
    recovery, so nothing downstream records a handoff GitHub never took.
    """
    for attempt in (0, 1):
        if attempt:
            sleep(confirm_seconds)
        membership, membership_error = read_membership(ctx, pr_num)
        state, _state_error = read_state(ctx, pr_num)
        if state is not None and state.merged:
            # The queue took it and merged it while the reads were running.
            return ""
        if landing_admitted(state, membership):
            return ""
    observed = describe_admission(membership, membership_error, state)
    if membership is None or state is None:
        return (
            f"the queue standing of pull request {pr_num} could not be read, "
            f"so its landing was not recorded as enqueued. Observed "
            f"{observed}. Fix the read failure and re-run `yoke merge item`."
        )
    return (
        f"pull request {pr_num} was not taken by the merge queue after the "
        f"merge-when-ready request: "
        f"{absence_reason(membership, state, target=target)}. "
        f"Observed {observed}."
    )


__all__ = [
    "ADMISSION_CONFIRM_SECONDS",
    "absence_reason",
    "describe_admission",
    "landing_admitted",
    "landing_eligible",
    "verify_landing_admitted",
]
