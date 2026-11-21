"""The words of one member's item-QA acceptance notice.

A run's acceptance answers only its own environment. When the member still
owes QA on another environment, the notice says this run owes nothing more
and names each owed entry and its target; it never calls the item's QA
gate clear while another environment still owes it.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.deployment_close_out_failure_summary import (
    close_out_failure_summary,
)
from yoke_core.domain.merge_queue_landing_notice import HOLDER

#: Blocker identity prefix for QA owed on another environment.
OWED_ELSEWHERE = "owed"


def owed_elsewhere_identities(owed: tuple[Any, ...]) -> tuple[str, ...]:
    """Stable identities for owed entries: no status, no prose, no commas."""
    return tuple(
        sorted(
            {
                f"{OWED_ELSEWHERE}:"
                + (
                    f"requirement-{entry.requirement_id}"
                    if entry.requirement_id is not None
                    else f"plan-{entry.plan_slug}"
                )
                + f"@{entry.target or '-'}"
                for entry in owed
            }
        )
    )


def _lead(public_ref: str, run_id: str, environment: str, owed: tuple[Any, ...]) -> str:
    if not owed:
        return (
            f"{public_ref}'s item-scoped QA gate is clear on deployment run "
            f"{run_id}. The run may still be executing; the selected flow's "
            "shared QA and approval gates decide whether sibling QA delays completion."
        )
    lines = [
        f"Deployment run {run_id} owes nothing more for {public_ref} on "
        f"{environment or 'its environment'}, but {public_ref} still owes QA "
        "on another environment:"
    ]
    for entry in owed:
        line = f"- {entry.label()} still owed on {entry.target or 'unspecified'}"
        lines.append(f"{line}: {entry.recovery}" if entry.recovery else line)
    lines.append(
        f"Read `yoke qa requirement list --item {public_ref}` and run each on "
        "that environment's deployment run."
    )
    return "\n".join(lines)


def item_qa_accepted_message(
    *,
    public_ref: str,
    run_id: str,
    route: str,
    close_out_failure: str = "",
    pending_credit: str = "",
    environment: str = "",
    owed: tuple[Any, ...] = (),
) -> str:
    """Name what was accepted, what is still owed, and how to wait."""
    lead = _lead(public_ref, run_id, environment, owed)
    if close_out_failure:
        lead += " " + close_out_failure_summary(public_ref, close_out_failure)
    recovery = (
        "Automatic close-out needs recovery before this item can finish. "
        if close_out_failure
        else "The completion flow will auto-close this item when its remaining delivery and QA obligations clear. "
    )
    if pending_credit:
        recovery = (
            f"{pending_credit} "
            + (recovery if close_out_failure else "")
            + "Automatic close-out retries when that credit arrives. "
        )
    if route == HOLDER:
        return (
            f"{lead} You hold its work claim and parked on this wait, so this "
            f"is your re-entry. {recovery}Check the item; do not re-run merge solely for "
            f"this acceptance. If the item is still at release wait, re-park "
            f"with `yoke sessions touch "
            f'--mode parked --reason "awaiting {public_ref} delivery"`.'
        )
    return (
        f"{lead} Nobody holds its work claim. {recovery}Check `yoke deployment-runs get "
        f"{run_id}` for run status and recovery."
    )


__all__ = [
    "OWED_ELSEWHERE",
    "item_qa_accepted_message",
    "owed_elsewhere_identities",
]
