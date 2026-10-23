"""What a session's live item claim still owes when its turn ends.

The Stop gate decides whether to hold a turn; this module decides what the
held claim actually means. Both readings are claim-shaped rather than
status-shaped, because status is not the signal for either of them: an item
can be past its own workflow's terminal stage, landed on the base branch but
not yet closed out, or armed in the merge queue waiting for a landing nobody
in this process can hasten — and only one of those is unfinished work the
session should be pushed back into.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.release_wait_park import at_release_wait
from yoke_core.domain.workflow_runtime import (
    ENGINE_TERMINAL_STAGE_IDS,
    ENGINE_WAIT_STAGE_IDS,
)


UNFINISHED_CLOSE_OUT = "lifecycle_close_out"
UNFINISHED_CLAIMED_ITEM = "claimed_item_in_progress"
DIRECTIVE = (
    "This session still holds a live work claim. Finish the current step "
    "if work remains; or release the claim if the work is finished or "
    "handed off; or stop deliberately and say why (blocked, waiting on "
    "the operator, parked)."
)
_HOLD_EXEMPT_STATUSES = ENGINE_TERMINAL_STAGE_IDS | ENGINE_WAIT_STAGE_IDS | {"done"}


def landed_but_open(claim: dict[str, Any]) -> bool:
    """Whether the branch already landed while the item stayed open."""
    return bool(claim.get("merged_at") or claim.get("merge_queue_landed_at"))


def waiting_on_landing(claim: dict[str, Any]) -> bool:
    """Whether the item is armed in the merge queue and has not landed yet.

    Recorded arming is what separates a session that stopped with work left
    from one whose remaining work belongs to GitHub. Nothing this session can
    do shortens that wait, and the control-plane landing observer messages the
    claim holder when it resolves, so stopping here is the designed handoff.

    A re-land's arming lives on the item's open attempt while the item's own
    stamps still describe the earlier landing, so an armed open attempt
    (``open_attempt_enqueued_at``) is the in-flight landing and wins.
    """
    if claim.get("open_attempt_enqueued_at"):
        return True
    return bool(claim.get("merge_queue_enqueued_at")) and not landed_but_open(claim)


def landing_notice_pending(claim: dict[str, Any]) -> bool:
    """Whether a queue landing's holder has yet to act on its landing notice.

    After a queued PR merges, the landing observer messages the claim holder
    and stamps ``merge_queue_notified_at``. Until the holder has been active
    (``last_tool_call_at``) after that notice, its silence is the notice in
    flight, not an idle worker. Once it acts, or the item closes, normal idle
    rules apply again. With no notice recorded nothing excuses the silence,
    so a notice that was never delivered still alarms.
    """
    if not claim.get("merge_queue_landed_at"):
        return False
    if str(claim.get("status") or "").strip() in _HOLD_EXEMPT_STATUSES:
        return False
    notified = claim.get("merge_queue_notified_at")
    if not notified:
        return False
    active = claim.get("last_tool_call_at")
    return not active or parse_instant(active) <= parse_instant(notified)


def stop_is_legitimate(claim: dict[str, Any]) -> bool:
    """Whether ending the turn on this claim needs no reminder."""
    status = str(claim.get("status") or "").strip()
    if status in _HOLD_EXEMPT_STATUSES or waiting_on_landing(claim):
        return True
    pin = {"id": claim.get("workflow_id"), "version": claim.get("workflow_version")}
    return at_release_wait({"workflow": pin}, status)


def unfinished_work_name(claim: dict[str, Any]) -> str:
    """Name the work the cap is about to abandon."""
    if landed_but_open(claim):
        return UNFINISHED_CLOSE_OUT
    return UNFINISHED_CLAIMED_ITEM


def recovery_for(claim: dict[str, Any]) -> str:
    """Recovery the next agent can run; status is never the landing signal."""
    ref = str(claim.get("item_id") or "")
    status = str(claim.get("status") or "")
    if landed_but_open(claim):
        return (
            f"item {ref} is still {status} after landing; status is not the "
            "landing signal. Finish close-out with "
            f"`yoke merge item {ref}` (Dash) or `/yoke usher {ref}` "
            "(delivery). Confirm merged_at, the merge receipt, or git "
            "ancestry of the merge sha."
        )
    return DIRECTIVE


__all__ = [
    "DIRECTIVE",
    "UNFINISHED_CLAIMED_ITEM",
    "UNFINISHED_CLOSE_OUT",
    "landed_but_open",
    "landing_notice_pending",
    "recovery_for",
    "stop_is_legitimate",
    "unfinished_work_name",
    "waiting_on_landing",
]
