"""Prove GitHub holds a landing before recording its handoff.

Admission requires a viable queue entry, or an armed eligible PR still waiting
on its checks. An armed PR that is ready yet holds no entry is not admitted:
arming does not queue it. A bounded read-back (one re-read after
``ADMISSION_CONFIRM_SECONDS``) confirms membership, eligibility and checks.
Cancelled checks recover before admission, independently of duplicate arming.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from yoke_core.domain.merge_queue_missing_checks import (
    ActiveWorkflowRun,
    readback_missing_checks_stalled,
    missing_checks_description,
    missing_checks_recovery,
    complete_missing_checks_readback,
    name_missing_checks,
)
from yoke_core.domain.merge_queue_absence_reasons import (
    ARMED_READY_REASON,
    absence_reason,
)
from yoke_core.domain.merge_queue_entry_check_redispatch import (
    redispatch_no_verdict_checks,
)
from yoke_core.domain.merge_queue_entry_checks import (
    describe_failed_checks,
    failed_required_checks,
    only_no_verdict,
    red_checks_recovery,
    regate_instruction,
)
from yoke_core.domain.merge_queue_readback_outcomes import (
    MERGE_WHEN_READY_ARMED,
    MERGE_WHEN_READY_CLEARED,
    MERGE_WHEN_READY_CONSUMED,
)
from yoke_core.domain.merge_github_check_runs import (
    LandingCheck,
    read_required_checks,
)
from yoke_core.domain.merge_github_membership import (
    PrQueueMembership,
    read_pr_queue_membership,
)
from yoke_core.domain.merge_github_queue import (
    READY_TO_ENQUEUE,
    PrLandingState,
    read_pr_landing_state,
)
from yoke_core.domain.merge_context import MergeContext


#: Grace before an absent queue entry is reported, in seconds.
ADMISSION_CONFIRM_SECONDS = 10.0

def landing_eligible(state: Optional[PrLandingState]) -> bool:
    """False once GitHub cannot create this pull request's merge commit."""
    if state is None:
        return False
    if state.closed:
        return False
    return (state.merge_state_status or "").strip().lower() != "dirty"


@dataclass(frozen=True)
class LandingReadback:
    """The facts one admission decision is made from, read together."""

    state: Optional[PrLandingState] = None
    membership: Optional[PrQueueMembership] = None
    required_checks: Optional[tuple[LandingCheck, ...]] = None
    state_error: str = ""
    membership_error: str = ""
    checks_error: str = ""
    queue_recovery: dict = field(default_factory=dict)
    missing_checks: tuple[str, ...] | None = None
    active_run: Optional[ActiveWorkflowRun] = None

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
        """True when GitHub is holding this landing."""
        if self.state is None or self.membership is None:
            return False
        if self.membership.entry_state == "UNMERGEABLE":
            return False
        if self.membership.in_queue:
            return True
        if self.failed_required or readback_missing_checks_stalled(self):
            return False
        return self.state.auto_merge_active and landing_eligible(self.state) and (
            not self.armed_ready()
        )

    def armed_ready(self) -> bool:
        """Armed and queueable now: arming alone never queues this state."""
        state = self.state
        return bool(state and state.auto_merge_active) and (
            state.merge_state_status in READY_TO_ENQUEUE
        )

    def undetermined(self) -> bool:
        """Open and unrefused, but GitHub has not decided: mid-merge, or an
        UNMERGEABLE entry whose mergeability it is still recomputing."""
        state, member = self.state, self.membership
        if state is None or state.merged or state.closed or self.failed_required:
            return False
        merge_state = (state.merge_state_status or "").lower()
        if member is not None and member.entry_state == "UNMERGEABLE":
            decided = (
                member.mergeable in {"MERGEABLE", "CONFLICTING"}
                or self.queue_recovery.get("action") == "blocked"
            )
            return not decided and merge_state != "dirty"
        refused = member is not None and member.mergeable == "CONFLICTING"
        return not refused and merge_state == "unknown"

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
            + missing_checks_description(self)
        )

    def recovery(self, *, target: str) -> str:
        """Why GitHub is not going to land this, and what to do about it."""
        state = self.state
        if state is not None and state.closed:
            return "it is closed — reopen or recreate it and re-run `yoke merge item`"
        if readback_missing_checks_stalled(self):
            return missing_checks_recovery(self.missing_checks, self.active_run)
        failed = self.failed_required
        if failed:
            return red_checks_recovery(failed)
        if self.armed_ready():
            return ARMED_READY_REASON
        from yoke_core.domain.merge_queue_ejection_recovery import recovery_instruction

        instruction = recovery_instruction(self, target=target)
        if instruction:
            return instruction
        merge_state = (state.merge_state_status if state is not None else "").strip()
        if (
            self.membership
            and self.membership.mergeable == "MERGEABLE"
            and merge_state.lower() == "dirty"
        ):
            merge_state = ""
        return absence_reason(merge_state, target=target)


def admission_facts_for_state(
    ctx: MergeContext,
    pr_num: str,
    state: Optional[PrLandingState],
    state_error: str = "",
    *,
    read_membership: Callable[..., object] = read_pr_queue_membership,
    read_checks: Callable[..., object] = read_required_checks,
) -> LandingReadback:
    """Complete admission facts without re-reading a known landing state."""
    from yoke_core.domain.merge_queue_failed_train import failed_train_readback

    if state is None or state.merged:
        return LandingReadback(state=state, state_error=state_error)
    membership, membership_error = read_membership(ctx, pr_num)
    state, checks, checks_error = complete_missing_checks_readback(
        ctx, pr_num, state, read_checks
    )
    readback = LandingReadback(
        state=state,
        membership=membership,
        required_checks=checks,
        membership_error=membership_error or "",
        checks_error=checks_error or "",
    )
    return failed_train_readback(ctx, pr_num, name_missing_checks(ctx, readback))


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
    """Confirm GitHub holds the landing, or name its refusal and recovery."""
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
    from yoke_core.domain.merge_queue_ejection_recovery import snapshot_recovery

    readback = snapshot_recovery(ctx, pr_num, readback)
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
    """Recover no-verdict checks and refuse a red, unadmitted candidate."""
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
