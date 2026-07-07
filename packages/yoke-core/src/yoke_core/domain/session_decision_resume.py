"""Resume-branch decision helper for session offers."""

from __future__ import annotations

from typing import Dict, List, Optional

from .session_contract import ActionKind, ClaimedWork, FrontierState, NextAction, SessionOffer
from .session_decision_freshness import (
    FreshnessOutcome,
    evaluate_freshness,
)
from .session_decision_lane_gate import LaneGateVerdict, evaluate_lane_gate


def decide_resume_action(
    offer: SessionOffer,
    frontier: FrontierState,
    claim: ClaimedWork,
    correlation: str,
    lane_allowed_paths: Optional[Dict[str, List[str]]],
) -> NextAction:
    required_path = claim.required_path
    ctx = {}
    if claim.item_id:
        ctx["item_id"] = claim.item_id
    if claim.epic_id is not None:
        ctx["epic_id"] = claim.epic_id
    if claim.task_num is not None:
        ctx["task_num"] = claim.task_num
    if claim.status:
        ctx["status"] = claim.status
    if required_path:
        ctx["required_path"] = required_path

    if required_path and offer.supported_paths and required_path not in offer.supported_paths:
        return NextAction(
            action=ActionKind.ESCALATE,
            reason=(
                f"Claimed work requires path '{required_path}' "
                f"but session only supports {offer.supported_paths}."
            ),
            chainable=False,
            correlation_id=correlation,
            context={
                **ctx,
                "escalate_reason": "unsupported_path",
                "required_path": required_path,
                "supported_paths": offer.supported_paths,
            },
        )

    if required_path and lane_allowed_paths:
        gate = evaluate_lane_gate(
            execution_lane=offer.execution_lane,
            required_path=required_path,
            lane_allowed_paths=lane_allowed_paths,
        )
        if gate.is_blocked:
            reason = (
                f"Lane '{offer.execution_lane or 'primary'}' is not configured "
                f"to run path '{required_path}' for claimed work."
                if gate.verdict is LaneGateVerdict.WAIT_DISALLOWED
                else (
                    f"Lane '{offer.execution_lane or 'primary'}' is unknown to "
                    f"lane policy; declare lane_paths_<lane> in machine config "
                    f"before routing claimed work on path '{required_path}'."
                )
            )
            return NextAction(
                action=ActionKind.WAIT,
                reason=reason,
                chainable=False,
                correlation_id=correlation,
                context={**ctx, **gate.wait_context()},
            )

    if (
        required_path
        and claim.item_id
        and claim.status
        and claim.epic_id is None
        and claim.task_num is None
    ):
        verdict = evaluate_freshness(
            item_id=claim.item_id,
            expected_status=claim.status,
            expected_next_step=required_path,
            scheduler_context=None,
            supported_paths=list(offer.supported_paths or []),
            execution_lane=offer.execution_lane,
            lane_allowed_paths=lane_allowed_paths,
            session_id=offer.session_id,
            chain_step=offer.step,
        )
        if verdict.outcome is FreshnessOutcome.UNSERVICEABLE:
            wait_ctx = dict(verdict.wait_context or {})
            wait_ctx.setdefault("item_id", claim.item_id)
            return NextAction(
                action=ActionKind.WAIT,
                reason=(
                    f"Claimed item {claim.item_id} moved to "
                    f"'{verdict.current_status}' before dispatch; live "
                    f"required_path is not serviceable by this lane/session."
                ),
                chainable=False,
                correlation_id=correlation,
                context=wait_ctx,
            )
        if (
            verdict.outcome is FreshnessOutcome.REWRITE
            and verdict.current_next_step
            and verdict.current_status
        ):
            required_path = verdict.current_next_step
            ctx["status"] = verdict.current_status
            ctx["required_path"] = required_path
            ctx["freshness_refreshed"] = True
            ctx["from_status"] = claim.status
            claim = ClaimedWork(
                item_id=claim.item_id,
                epic_id=claim.epic_id,
                task_num=claim.task_num,
                status=verdict.current_status,
                item_type=claim.item_type,
                required_path=required_path,
            )

    if offer.step > 1 and frontier.last_completed_step:
        last = frontier.last_completed_step
        same_work = (
            last.get("action") == "resume"
            and last.get("item_id") == claim.item_id
            and last.get("task_num") == claim.task_num
        )
        same_disposition = last.get("handler_outcome", "completed") == "completed"
        # Direct progress measurement: did the prior handler actually move the
        # item? The checkpoint's pre_status records the offer-time status
        # before the handler ran; status records where the handler landed.
        # When pre_status differs from status, the handler advanced the item
        # — that's progress, not stuck state — and we must NOT escalate even
        # if the new offer happens to land on the same status name.
        #
        # Backfill fallback: when last.pre_status is missing/empty (older
        # in-flight chains, or any caller that has not yet been updated), fall
        # back to the legacy same_state heuristic (status match OR path match)
        # so previously-deployed sessions keep their existing escalate
        # behavior. Remove the fallback once pre_status has been populated for
        # ≥ one stale-session-TTL window (tracked separately).
        last_pre_status = last.get("pre_status")
        last_status = last.get("status")
        if last_pre_status:
            progress = bool(last_status and last_pre_status != last_status)
            stuck = not progress
        else:
            stuck = (
                (claim.status is not None and last_status == claim.status)
                or (required_path is not None and last.get("required_path") == required_path)
            )
        if same_work and same_disposition and stuck:
            return NextAction(
                action=ActionKind.ESCALATE,
                reason=(
                    f"Repeated resume for {claim.item_id} at same status "
                    f"'{claim.status}' / path '{required_path}' with no progress."
                ),
                chainable=False,
                correlation_id=correlation,
                context={
                    **ctx,
                    "escalate_reason": "resume_no_progress",
                    "required_path": required_path,
                },
            )

    return NextAction(
        action=ActionKind.RESUME,
        reason=f"Session has active claimed work ({claim.item_id or f'epic task {claim.epic_id}/{claim.task_num}'}).",
        chainable=True,
        correlation_id=correlation,
        context=ctx,
    )
