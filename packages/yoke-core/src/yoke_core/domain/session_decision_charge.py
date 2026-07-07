"""Charge-branch decision helper for session offers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .session_contract import ActionKind, FrontierState, NextAction, SessionOffer
from .session_decision_freshness import (
    FreshnessOutcome,
    evaluate_freshness,
)
from .session_decision_lane_gate import LaneGateVerdict, evaluate_lane_gate

_NEXT_STEP_TO_PATH: Dict[str, str] = {
    "refine": "refine",
    "shepherd": "shepherd",
    "conduct": "conduct",
    "advance": "advance",
    "polish": "polish",
    "usher": "usher",
}


def build_charge_context(frontier: FrontierState) -> Dict[str, Any]:
    """Canonical charge-context shape for scheduler-backed charge actions.

    Returns a dict with ``selected_item`` + ``runnable_items`` + (when
    ``frontier.scheduler_context`` is set) the ``scheduler`` block. Both
    the normal charge branch and the disabled-process fallback in
    ``session_decision_process_gate.apply_process_offer_gate`` build
    from this helper so a future scheduler-context field cannot drift
    between the two paths.
    """
    ctx: Dict[str, Any] = {
        "selected_item": frontier.selected_item,
        "runnable_items": list(frontier.runnable_items),
    }
    if frontier.scheduler_context:
        ctx["scheduler"] = frontier.scheduler_context
    return ctx


def decide_charge_action(
    offer: SessionOffer,
    frontier: FrontierState,
    correlation: str,
    lane_allowed_paths: Optional[Dict[str, List[str]]],
) -> Optional[NextAction]:
    if frontier.selected_item and frontier.sml_coherent:
        next_step_raw = ""
        required_path = None
        if frontier.scheduler_context:
            next_step_raw = frontier.scheduler_context.get("next_step", "")
            required_path = _NEXT_STEP_TO_PATH.get(next_step_raw)

            # Refuse a routed charge when the selected schedule block has
            # no dispatchable route; the offer adapter reconciles any
            # eager claim before returning the non-charge action.
            if not next_step_raw or required_path is None:
                return NextAction(
                    action=ActionKind.WAIT,
                    reason=(
                        f"Charge target {frontier.selected_item} has a "
                        f"scheduler context with no usable next_step "
                        f"(raw={next_step_raw!r}); dispatch refused."
                    ),
                    chainable=False,
                    correlation_id=correlation,
                    context={
                        "wait_reason": "missing_scheduler_next_step",
                        "selected_item": frontier.selected_item,
                        "scheduler_context": frontier.scheduler_context,
                    },
                )

            scheduler_item = frontier.scheduler_context.get("selected_item")
            if scheduler_item and scheduler_item != frontier.selected_item:
                return NextAction(
                    action=ActionKind.WAIT,
                    reason=(
                        f"Scheduler context names selected_item="
                        f"{scheduler_item!r} but offer-time claim is for "
                        f"{frontier.selected_item!r}; dispatch refused."
                    ),
                    chainable=False,
                    correlation_id=correlation,
                    context={
                        "wait_reason": "scheduler_context_item_mismatch",
                        "selected_item": frontier.selected_item,
                        "scheduler_selected_item": scheduler_item,
                    },
                )

        if offer.supported_paths and frontier.scheduler_context:
            if required_path and required_path not in offer.supported_paths:
                return NextAction(
                    action=ActionKind.ESCALATE,
                    reason=(
                        f"Selected item requires path '{required_path}' "
                        f"but session only supports {offer.supported_paths}."
                    ),
                    chainable=False,
                    correlation_id=correlation,
                    context={
                        "escalate_reason": "unsupported_path",
                        "required_path": required_path,
                        "supported_paths": offer.supported_paths,
                        "selected_item": frontier.selected_item,
                    },
                )

        if frontier.scheduler_context and required_path:
            gate = evaluate_lane_gate(
                execution_lane=offer.execution_lane,
                required_path=required_path,
                lane_allowed_paths=lane_allowed_paths,
            )
            if gate.is_blocked:
                reason = (
                    f"Lane '{offer.execution_lane or 'primary'}' is not configured "
                    f"to run path '{required_path}'."
                    if gate.verdict is LaneGateVerdict.WAIT_DISALLOWED
                    else (
                        f"Lane '{offer.execution_lane or 'primary'}' is unknown to "
                        f"lane policy; declare lane_paths_<lane> in machine config "
                        f"before routing path '{required_path}'."
                    )
                )
                ctx = gate.wait_context()
                ctx["actual_lane"] = offer.execution_lane
                ctx["next_step"] = next_step_raw
                ctx["selected_item"] = frontier.selected_item
                return NextAction(
                    action=ActionKind.WAIT,
                    reason=reason,
                    chainable=False,
                    correlation_id=correlation,
                    context=ctx,
                )
        scheduler_status = (
            frontier.scheduler_context.get("status")
            if frontier.scheduler_context else None
        )
        if frontier.scheduler_context and scheduler_status and next_step_raw:
            verdict = evaluate_freshness(
                item_id=frontier.selected_item,
                expected_status=scheduler_status,
                expected_next_step=next_step_raw,
                scheduler_context=frontier.scheduler_context,
                supported_paths=list(offer.supported_paths or []),
                execution_lane=offer.execution_lane,
                lane_allowed_paths=lane_allowed_paths,
                session_id=offer.session_id,
                chain_step=offer.step,
            )
            if verdict.outcome is FreshnessOutcome.UNSERVICEABLE:
                wait_ctx = dict(verdict.wait_context or {})
                wait_ctx.setdefault("selected_item", frontier.selected_item)
                return NextAction(
                    action=ActionKind.WAIT,
                    reason=(
                        f"Charge target {frontier.selected_item} moved to "
                        f"'{verdict.current_status}' before dispatch; live "
                        f"next_step is not serviceable by this lane/session."
                    ),
                    chainable=False,
                    correlation_id=correlation,
                    context=wait_ctx,
                )
            if verdict.outcome is FreshnessOutcome.REWRITE and verdict.refreshed_context:
                frontier = FrontierState(
                    runnable_items=list(frontier.runnable_items),
                    blocked_items=list(frontier.blocked_items),
                    exceptional_items=list(frontier.exceptional_items),
                    blocked_details=frontier.blocked_details,
                    sml_coherent=frontier.sml_coherent,
                    drift_review=frontier.drift_review,
                    selected_item=frontier.selected_item,
                    scheduler_context=verdict.refreshed_context,
                    lane_filtered_count=frontier.lane_filtered_count,
                    lane_filtered_items=frontier.lane_filtered_items,
                    last_completed_step=frontier.last_completed_step,
                )
        charge_ctx = build_charge_context(frontier)
        return NextAction(
            action=ActionKind.CHARGE,
            reason=f"{len(frontier.runnable_items)} runnable item(s) on the frontier; selected {frontier.selected_item}.",
            chainable=True,
            correlation_id=correlation,
            context=charge_ctx,
        )

    if frontier.runnable_items and frontier.sml_coherent and frontier.scheduler_context is None:
        return NextAction(
            action=ActionKind.CHARGE,
            reason=f"{len(frontier.runnable_items)} runnable item(s) on the frontier.",
            chainable=True,
            correlation_id=correlation,
            context={"runnable_items": frontier.runnable_items},
        )
    return None
