"""Prove GitHub holds a landing before recording its handoff.

Admission requires a viable queue entry, or an armed eligible PR without red
required checks. Arming is a request, never evidence that GitHub accepted it.
A bounded read-back confirms membership, eligibility and required-check state.
Cancelled checks recover before admission, independently of duplicate arming.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from yoke_core.domain.merge_queue_entry_check_redispatch import (
    redispatch_no_verdict_checks,
)
from yoke_core.domain.merge_queue_entry_checks import (
    describe_failed_checks,
    failed_required_checks,
    only_no_verdict,
    regate_instruction,
)
from yoke_core.domain.merge_queue_readback_outcomes import (
    MERGE_WHEN_READY_ARMED,
    MERGE_WHEN_READY_CLEARED,
    MERGE_WHEN_READY_CONSUMED,
)
from yoke_core.engines.merge_worktree_pr_check_runs import (
    LandingCheck,
    read_required_checks,
)
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


@dataclass(frozen=True)
class LandingReadback:
    """The four facts one admission decision is made from, read together."""

    state: Optional[PrLandingState] = None
    membership: Optional[PrQueueMembership] = None
    required_checks: Optional[tuple[LandingCheck, ...]] = None
    state_error: str = ""
    membership_error: str = ""
    checks_error: str = ""

    @property
    def failed_required(self) -> tuple[LandingCheck, ...]:
        """Required checks already concluded red; empty when unreadable."""
        return failed_required_checks(self.required_checks)

    @property
    def readable(self) -> bool:
        """Whether both facts an admission cannot be decided without answered."""
        return self.state is not None and self.membership is not None

    @property
    def merged(self) -> bool:
        return self.state is not None and self.state.merged

    def admitted(self) -> bool:
        """True when GitHub is holding this landing.

        A queue entry settles it unless its state is UNMERGEABLE.
        GitHub can retain unmergeable entries, but cannot land them.
        Without an entry the landing must be armed, eligible, and not already
        refused by its own required checks — which together are the
        ordinary armed-and-waiting state before those checks pass.

        An unreadable pull request, membership, or rollup is not an
        admission — it proves nothing — but it is not a refusal either;
        callers distinguish the two.
        """
        if self.state is None or self.membership is None:
            return False
        if self.membership.entry_state == "UNMERGEABLE":
            return False
        if self.membership.in_queue:
            return True
        if self.failed_required:
            return False
        return self.state.auto_merge_active and landing_eligible(self.state)

    def describe(self) -> str:
        """The four fields behind an admission decision, as named readings."""
        if self.membership is not None:
            queue = self.membership.describe()
        else:
            queue = (
                "queue membership unreadable "
                f"({self.membership_error or 'no reason given'})"
            )
        state = self.state
        merge_state = (state.merge_state_status if state is not None else "") or (
            "unreported"
        )
        if state is None:
            armed = f"unreadable ({self.state_error or 'no reason given'})"
        else:
            armed = (
                MERGE_WHEN_READY_ARMED
                if state.auto_merge_active
                else MERGE_WHEN_READY_CONSUMED
                if self.membership is not None and self.membership.in_queue
                else MERGE_WHEN_READY_CLEARED
            )
        if self.required_checks is None:
            checks = f"unreadable ({self.checks_error or 'no reason given'})"
        else:
            checks = describe_failed_checks(self.failed_required)
        return (
            f"merge-when-ready={armed}, {queue}, "
            f"mergeStateStatus={merge_state.upper()}, "
            f"failed-required-checks={checks}"
        )

    def recovery(self, *, target: str) -> str:
        """Why GitHub is not going to land this, and what to do about it."""
        state = self.state
        if state is not None and state.closed:
            return "it is closed — reopen or recreate it and re-run `yoke merge item`"
        failed = self.failed_required
        if failed:
            return regate_instruction(failed)
        merge_state = (state.merge_state_status if state is not None else "").strip()
        if self.membership is not None:
            if self.membership.entry_state == "UNMERGEABLE":
                merge_state = "dirty"
            elif self.membership.mergeable == "CONFLICTING":
                merge_state = merge_state or "dirty"
        template = _ABSENCE_REASONS.get(merge_state.lower(), _DEFAULT_ABSENCE_REASON)
        return template.format(target=target)


def admission_facts_for_state(
    ctx: MergeContext,
    pr_num: str,
    state: Optional[PrLandingState],
    state_error: str = "",
    *,
    read_membership: Callable[..., object] = read_pr_queue_membership,
    read_checks: Callable[..., object] = read_required_checks,
) -> LandingReadback:
    """Complete the admission facts for a landing state already read.

    A merged or unreadable pull request stops there: the queue standing
    and required checks of a landing that is already over answer nothing
    the caller is about to decide. Callers that read the state for their
    own reasons first finish the set here instead of reading it twice.
    """
    if state is None or state.merged:
        return LandingReadback(state=state, state_error=state_error)
    membership, membership_error = read_membership(ctx, pr_num)
    checks, checks_error = read_checks(ctx, pr_num)
    return LandingReadback(
        state=state,
        membership=membership,
        required_checks=checks,
        membership_error=membership_error or "",
        checks_error=checks_error or "",
    )


def read_landing(
    ctx: MergeContext,
    pr_num: str,
    *,
    read_state: Callable[..., object] = read_pr_landing_state,
    read_membership: Callable[..., object] = read_pr_queue_membership,
    read_checks: Callable[..., object] = read_required_checks,
) -> LandingReadback:
    """Read the four admission facts for ``pr_num`` in one pass."""
    state, state_error = read_state(ctx, pr_num)
    return admission_facts_for_state(
        ctx,
        pr_num,
        state,
        state_error or "",
        read_membership=read_membership,
        read_checks=read_checks,
    )


def verify_landing_admitted(
    ctx: MergeContext,
    pr_num: str,
    *,
    target: str = "main",
    sleep: Callable[[float], None],
    confirm_seconds: float = ADMISSION_CONFIRM_SECONDS,
    read_membership: Callable[..., object] = read_pr_queue_membership,
    read_state: Callable[..., object] = read_pr_landing_state,
    read_checks: Callable[..., object] = read_required_checks,
) -> str:
    """Return ``""`` once GitHub reports it is holding the landing for ``pr_num``.

    Any other outcome — an admission GitHub never made, a landing its own
    required checks have already refused, or reads that cannot answer —
    returns a refusal naming all four fields and the recovery, so nothing
    downstream records a handoff GitHub never took.
    """
    for attempt in (0, 1):
        if attempt:
            sleep(confirm_seconds)
        readback = read_landing(
            ctx,
            pr_num,
            read_state=read_state,
            read_membership=read_membership,
            read_checks=read_checks,
        )
        if readback.merged:
            # The queue took it and merged it while the reads were running.
            return ""
        if readback.admitted():
            return ""
    observed = readback.describe()
    if not readback.readable:
        return (
            f"the queue standing of pull request {pr_num} could not be read, "
            f"so its landing was not recorded as enqueued. Observed "
            f"{observed}. Fix the read failure and re-run `yoke merge item`."
        )
    return (
        f"pull request {pr_num} was not taken by the merge queue after the "
        f"merge-when-ready request: {readback.recovery(target=target)}. "
        f"Observed {observed}."
    )


def red_entry_checks_refusal(
    ctx: MergeContext,
    pr_num: str,
    *,
    read_checks: Callable[..., object] = read_required_checks,
    sleep: Callable[[float], None] = time.sleep,
    lane_head: str = "",
    armed: bool = False,
) -> str:
    """Refuse to arm a pull request its required checks have already failed.

    Arming a red pull request is not harmless: merge-when-ready takes, so
    every downstream read sees an armed landing and waits for a queue
    entry GitHub is never going to create. Reading the rollup before the
    mutation is what keeps the ordering honest. An unreadable rollup is
    not a refusal — the admission read-back after arming asks again.

    A set whose only red checks were cancelled or never started is not
    refused: those checks are re-run on the same head, and arming proceeds
    once GitHub shows them replaced.
    """
    if armed:
        facts = read_landing(ctx, pr_num, read_checks=read_checks)
        if facts.merged or (facts.state and facts.state.closed):
            return ""
        if not facts.readable:
            return f"ci_recovery_unreadable: {facts.describe()}. Restore GitHub reads and retry merge; no rerun was sent."
        if facts.admitted() or not landing_eligible(facts.state):
            return ""
        checks, checks_error = facts.required_checks, facts.checks_error
    else:
        checks, checks_error = read_checks(ctx, pr_num)
    if checks_error or checks is None:
        return ""
    failed = failed_required_checks(checks)
    if not failed:
        return ""
    if only_no_verdict(failed):
        return redispatch_no_verdict_checks(
            ctx,
            pr_num,
            failed,
            read_checks=read_checks,
            sleep=sleep,
            lane_head=lane_head,
        )
    action = "cannot enter" if armed else "was not armed for"
    return (
        f"pull request {pr_num} {action} the merge queue: {regate_instruction(failed)}."
    )


__all__ = [
    "ADMISSION_CONFIRM_SECONDS",
    "LandingReadback",
    "admission_facts_for_state",
    "landing_eligible",
    "read_landing",
    "red_entry_checks_refusal",
    "verify_landing_admitted",
]
