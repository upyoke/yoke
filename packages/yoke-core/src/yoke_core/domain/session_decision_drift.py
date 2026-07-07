"""Drift-review decision helpers for session offers."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .session_contract import ActionKind, FrontierState, NextAction
from .session_decision_context import _apply_lane_filtered_signal


def decide_drift_review_action(
    frontier: FrontierState,
    correlation: str,
) -> Optional[NextAction]:
    if not (frontier.drift_review and frontier.sml_coherent):
        return None
    classification = frontier.drift_review.get("classification", "neither")
    summary = frontier.drift_review.get("summary", "")
    review_ctx = {
        "classification": classification,
        "summary": summary,
        "checkpoint_start": frontier.drift_review.get("checkpoint_start", ""),
        "reviewed_through": frontier.drift_review.get("reviewed_through", ""),
        "delivered_items": frontier.drift_review.get("delivered_items", []),
    }

    if classification == "both":
        return NextAction(
            action=ActionKind.STRATEGIZE,
            reason=f"Drift review: both SML and frontier impacted. {summary}",
            chainable=False,
            correlation_id=correlation,
            context={
                "sml_coherent": True,
                "trigger": "drift_review",
                "drift_review": review_ctx,
                "follow_on": "feed",
            },
        )

    if classification == "sml_only":
        return NextAction(
            action=ActionKind.STRATEGIZE,
            reason=f"Drift review: SML impacted. {summary}",
            chainable=False,
            correlation_id=correlation,
            context={
                "sml_coherent": True,
                "trigger": "drift_review",
                "drift_review": review_ctx,
            },
        )

    if classification == "frontier_only":
        drift_feed_ctx = {
            "blocked_count": len(frontier.blocked_items),
            "trigger": "drift_review",
            "drift_review": review_ctx,
        }
        _apply_lane_filtered_signal(drift_feed_ctx, frontier)
        return NextAction(
            action=ActionKind.FEED,
            reason=f"Drift review: frontier impacted. {summary}",
            chainable=False,
            correlation_id=correlation,
            context=drift_feed_ctx,
        )
    return None


def build_drift_review_failure_action(
    correlation_id: str,
    error: str,
) -> NextAction:
    return NextAction(
        action=ActionKind.ESCALATE,
        reason=(
            "Post-delivery drift review failed; human intervention is "
            "required before Yoke can choose the next strategy/frontier step."
        ),
        chainable=False,
        correlation_id=correlation_id,
        context={"trigger": "drift_review", "error": error},
    )


def should_emit_drift_review_checkpoint(
    result: NextAction,
    drift_review: Optional[Dict[str, Any]],
) -> bool:
    if not drift_review:
        return False
    classification = drift_review.get("classification")
    if classification == "neither":
        return True
    if classification != "frontier_only":
        return False
    if not result.context:
        return False
    if (
        result.action == ActionKind.FEED
        and result.context.get("trigger") == "drift_review"
    ):
        return True
    if result.action == ActionKind.WAIT:
        suppressed = result.context.get("suppressed_process_recommendation")
        if isinstance(suppressed, dict):
            original = suppressed.get("original_context") or {}
            if isinstance(original, dict) and original.get("trigger") == "drift_review":
                return True
    return False
