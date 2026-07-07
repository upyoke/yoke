"""Pure next-action decision engine for session offers."""

from __future__ import annotations

from typing import Dict, List, Optional

from yoke_core.api.routing_config import ProcessOfferPolicy

from .session_contract import ActionKind, ClaimedWork, FrontierState, NextAction, SessionOffer
from .session_decision_charge import _NEXT_STEP_TO_PATH, decide_charge_action
from .session_decision_context import (
    _apply_lane_filtered_signal,
    _lane_filtered_note,
    build_no_lane_compatible_work_context,
)
from .session_decision_drift import decide_drift_review_action
from .session_decision_process_gate import apply_process_offer_gate
from .session_decision_resume import decide_resume_action


def decide_next_action(
    offer: SessionOffer,
    frontier: FrontierState,
    active_claims: Optional[List[ClaimedWork]] = None,
    lane_allowed_paths: Optional[Dict[str, List[str]]] = None,
    process_offer_policy: Optional[ProcessOfferPolicy] = None,
) -> NextAction:
    claims = active_claims or []
    correlation = offer.session_id

    if claims:
        return decide_resume_action(
            offer,
            frontier,
            claims[0],
            correlation,
            lane_allowed_paths,
        )

    charge = decide_charge_action(offer, frontier, correlation, lane_allowed_paths)
    if charge is not None:
        return charge

    has_blockers = bool(frontier.blocked_items) or bool(frontier.exceptional_items)
    if has_blockers and not frontier.runnable_items:
        blocked_count = len(frontier.blocked_items)
        exceptional_count = len(frontier.exceptional_items)
        parts = []
        if blocked_count:
            parts.append(f"{blocked_count} blocked")
        if exceptional_count:
            parts.append(f"{exceptional_count} failed")
        escalate_ctx = {
            "blocked_items": frontier.blocked_items,
            "exceptional_items": frontier.exceptional_items,
        }
        if frontier.blocked_details:
            escalate_ctx["blocked_details"] = frontier.blocked_details
        if frontier.intrinsic_blocked_reasons:
            escalate_ctx["intrinsic_blocked_reasons"] = frontier.intrinsic_blocked_reasons
        _apply_lane_filtered_signal(escalate_ctx, frontier)
        return NextAction(
            action=ActionKind.ESCALATE,
            reason=f"All items require attention ({', '.join(parts)}); human intervention required.",
            chainable=False,
            correlation_id=correlation,
            context=escalate_ctx,
        )

    if (
        not frontier.runnable_items
        and not frontier.blocked_items
        and not frontier.exceptional_items
        and frontier.lane_filtered_count > 0
        and frontier.sml_coherent
    ):
        no_lane_ctx = build_no_lane_compatible_work_context(
            frontier, offer.execution_lane,
        )
        return NextAction(
            action=ActionKind.WAIT,
            reason=(
                f"{frontier.lane_filtered_count} frontier item(s) exist but are queued "
                f"for another lane; this lane has no compatible work right now."
            ),
            chainable=False,
            correlation_id=correlation,
            context=no_lane_ctx,
        )

    drift_action = decide_drift_review_action(frontier, correlation)
    if drift_action is not None:
        return apply_process_offer_gate(
            drift_action, frontier, correlation, process_offer_policy,
            lane_allowed_paths=lane_allowed_paths,
            execution_lane=offer.execution_lane,
        )

    if not frontier.runnable_items and frontier.sml_coherent:
        feed_ctx = {
            "blocked_count": len(frontier.blocked_items),
            "trigger": "no_runnable_items",
        }
        _apply_lane_filtered_signal(feed_ctx, frontier)
        feed_action = NextAction(
            action=ActionKind.FEED,
            reason="No runnable items but strategy is coherent; materialize more work.",
            chainable=False,
            correlation_id=correlation,
            context=feed_ctx,
        )
        return apply_process_offer_gate(
            feed_action, frontier, correlation, process_offer_policy,
            lane_allowed_paths=lane_allowed_paths,
            execution_lane=offer.execution_lane,
        )

    if not frontier.sml_coherent:
        strategize_action = NextAction(
            action=ActionKind.STRATEGIZE,
            reason="Strategic layer needs attention: SML is absent or incoherent.",
            chainable=False,
            correlation_id=correlation,
            context={"sml_coherent": frontier.sml_coherent},
        )
        return apply_process_offer_gate(
            strategize_action, frontier, correlation, process_offer_policy,
            lane_allowed_paths=lane_allowed_paths,
            execution_lane=offer.execution_lane,
        )

    return NextAction(
        action=ActionKind.WAIT,
        reason="No actionable work exists on the frontier.",
        chainable=False,
        correlation_id=correlation,
    )
