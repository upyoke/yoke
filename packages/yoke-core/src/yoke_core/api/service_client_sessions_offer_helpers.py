"""Helpers extracted from ``service_client_sessions_offer.cmd_session_offer``.

These cover the two ``action_hint=no_work`` branches — building the WAIT
directive directly when the ownership block could not acquire any candidate,
and validating the charge invariant before the offer is allowed to leave the
command — kept here so the host module stays under the 350-line authored
ceiling.

These helpers operate on the dict returned by
:func:`yoke_core.domain.sessions.session_offer_with_ownership` plus the
final :class:`yoke_core.domain.session_contract.NextAction`. They are
caller-facing only (no DB writes) so the cmd_session_offer transaction
boundary stays the same.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from yoke_core.domain.session_contract import ActionKind, NextAction
from yoke_core.domain.sessions_offer_revalidation import (
    build_no_work_wait_context,
    normalize_item_id,
)


def build_no_work_wait_action(
    *,
    session_id: str,
    ownership: Dict[str, Any],
    step: int,
) -> NextAction:
    """Construct a WAIT NextAction for the ``action_hint=no_work`` path.

    The WAIT directive replaces the legacy fall-through into
    ``decide_next_action`` over the unfiltered schedule (which used to
    return CHARGE for an item the offer-time ownership block already gave
    up on). The schedule is consulted only to surface ``lane_filtered_*``
    signals; the dispatch fields (``selected_item``, ``scheduler``) are
    intentionally absent so the operator-facing ``/yoke do`` loop has
    nothing to dispatch from.
    """
    schedule = ownership.get("schedule_result")
    lane_filtered_count = (
        getattr(schedule, "lane_filtered_count", 0) if schedule else 0
    )
    lane_filtered_items = (
        getattr(schedule, "lane_filtered_items", None) if schedule else None
    )
    wait_context = build_no_work_wait_context(
        terminal_reason=ownership.get("terminal_reason"),
        skip_memory=ownership.get("chain_skip_memory") or [],
        chain_step=step,
        lane_filtered_count=lane_filtered_count,
        lane_filtered_items=lane_filtered_items,
    )
    if wait_context["wait_reason"] == "all_runnable_items_blocked_by_live_claims":
        reason = (
            "All runnable frontier items are held by live claims on other "
            "sessions; this offer cannot acquire any of them."
        )
    else:
        reason = (
            "Offer-time revalidation skipped every candidate "
            f"(terminal_reason={wait_context['terminal_reason']}); no claim "
            "could be acquired."
        )
    return NextAction(
        action=ActionKind.WAIT,
        reason=reason,
        chainable=False,
        correlation_id=session_id,
        context=wait_context,
    )


def should_return_no_work_wait(ownership: Dict[str, Any], step: int) -> bool:
    """Return true when ``no_work`` came from offer-time skipped candidates."""
    if ownership.get("action_hint") != "no_work":
        return False
    return any(
        entry.get("chain_step") == step
        for entry in (ownership.get("chain_skip_memory") or [])
    )


def validate_charge_claim_invariant(
    result: NextAction,
    new_claim: Optional[Dict[str, Any]],
) -> Tuple[bool, Optional[str]]:
    """Confirm a CHARGE result is backed by a fresh claim on the dispatch target.

    Returns ``(True, None)`` for non-charge results and for charge results
    where ``new_claim`` is present and matches ``context.selected_item``.
    Otherwise returns ``(False, error_message)`` so the caller can surface
    the structural failure and refuse to emit a chargeable directive.

    A CHARGE without ``new_claim`` — or with a claim on a different item
    than ``context.selected_item`` — would send the operator into a
    guaranteed claim-work conflict downstream. Failing loudly here keeps the
    regression visible.
    """
    if result.action.value != "charge":
        return True, None
    ctx_selected = (result.context or {}).get("selected_item")
    if not new_claim:
        return False, (
            "charge action returned without a backing work claim "
            f"(selected_item={ctx_selected}). The ownership block could not "
            "acquire any candidate; refusing to emit a charge directive."
        )
    claim_item = new_claim.get("item_id")
    # selected_item is rendered as ``YOK-N`` while new_claim.item_id is the
    # bare integer; normalize both before comparing.
    selected_norm = normalize_item_id(ctx_selected)
    claim_norm = normalize_item_id(claim_item)
    if (
        selected_norm is not None
        and claim_norm is not None
        and selected_norm != claim_norm
    ):
        return False, (
            f"charge action selected_item={ctx_selected} does not match "
            f"new_claim item_id={claim_item}; refusing to emit a mismatched "
            "charge directive."
        )
    return True, None


__all__ = [
    "build_no_work_wait_action",
    "should_return_no_work_wait",
    "validate_charge_claim_invariant",
]
