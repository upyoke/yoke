"""Session analytics public import front door."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .sessions_analytics_core import (
    DEFAULT_PROGRESS_THRESHOLD_MINUTES,
    DEFAULT_STALE_THRESHOLD_MINUTES,
    EXECUTOR_STALE_TTL_OVERRIDES_MINUTES,
    EVENT_CHAIN_STEP_COMPLETED,
    EVENT_HARNESS_SESSION_ENDED,
    EVENT_HARNESS_SESSION_END_REJECTED_ACTIVE_CLAIM,
    EVENT_HARNESS_SESSION_END_RELEASED_CLAIMS,
    EVENT_HARNESS_SESSION_HOOK_FAILED,
    EVENT_HARNESS_SESSION_STALE_RECLAIMED,
    EVENT_HARNESS_SESSION_STALE_SWEEP_COMPLETED,
    EVENT_HARNESS_SESSION_STARTED,
    EVENT_ITEM_CLAIM_RELEASE_FAILED,
    EVENT_OPERATOR_CLAIM_OVERRIDE,
    EVENT_RECLAIM_ABORTED,
    EVENT_SESSION_REACTIVATED_WITH_RELEASED_CLAIMS,
    EVENT_WORK_CLAIMED,
    EVENT_WORK_HANDED_OFF,
    EVENT_WORK_RECLAIMED,
    EVENT_WORK_RELEASED,
    SessionError,
    _NEXT_STEP_TO_PATH,
    _SESSION_EVENT_REGISTRY_ROWS,
    _emit_event as _core_emit_event,
    ensure_session_event_registry_entries,
)
from .sessions_analytics_dispatch import (
    _resolve_resume_dispatch,
    emit_adapter_dispatch_chosen,
    emit_drift_review_completed,
    emit_lane_routing_decision,
    emit_next_action_chosen,
)

def _emit_event(
    event_name: str,
    *,
    event_kind: str,
    event_type: str,
    source_type: str,
    session_id: str,
    project: Optional[str] = None,
    item_id: Optional[str] = None,
    task_num: Optional[int] = None,
    context: Optional[Dict[str, Any]] = None,
    outcome: str = "completed",
    severity: str = "INFO",
) -> None:
    _core_emit_event(
        event_name,
        event_kind=event_kind,
        event_type=event_type,
        source_type=source_type,
        session_id=session_id,
        project=project,
        item_id=item_id,
        task_num=task_num,
        context=context,
        outcome=outcome,
        severity=severity,
    )


def _emit_session_event(
    event_name: str,
    *,
    session_id: str,
    item_id: Optional[str] = None,
    task_num: Optional[int] = None,
    context: Optional[Dict[str, Any]] = None,
    outcome: str = "completed",
) -> None:
    _emit_event(
        event_name,
        event_kind="system",
        event_type="session_lifecycle",
        source_type="backend",
        session_id=session_id,
        item_id=item_id,
        task_num=task_num,
        context=context,
        outcome=outcome,
    )

def emit_post_decision_telemetry(
    conn: Any,
    session_id: str,
    *,
    action: str,
    reason: str,
    actual_lane: str,
    context: Optional[Dict[str, Any]] = None,
    project: str = "yoke",
) -> None:
    """Emit shared post-decision telemetry for both CLI and HTTP adapters."""
    ctx = context or {}
    scheduler_ctx = ctx.get("scheduler", {})
    selected_item = ctx.get("selected_item") or ctx.get("item_id")
    next_step = scheduler_ctx.get("next_step", "")

    lane_decision = "allowed"
    lane_context: Dict[str, Any] = {}
    if ctx.get("wait_reason") in (
        "lane_policy_disallows_path",
        "lane_policy_unknown",
    ):
        lane_decision = "blocked_policy"
        if ctx.get("wait_reason"):
            lane_context["wait_reason"] = ctx["wait_reason"]
        if ctx.get("required_path"):
            lane_context["required_path"] = ctx["required_path"]
        if ctx.get("allowed_paths") is not None:
            lane_context["allowed_paths"] = ctx["allowed_paths"]
        if ctx.get("unknown_lane") is not None:
            lane_context["unknown_lane"] = ctx["unknown_lane"]
        if ctx.get("configured_lanes") is not None:
            lane_context["configured_lanes"] = ctx["configured_lanes"]

    emit_lane_routing_decision(
        session_id,
        project=project,
        actual_lane=actual_lane,
        selected_item=selected_item,
        next_step=next_step,
        decision=lane_decision,
        context=lane_context or None,
    )

    adapter = _NEXT_STEP_TO_PATH.get(next_step, next_step) if next_step else ""
    dispatch_source = "scheduler.next_step" if next_step else ""
    dispatch_context: Dict[str, Any] = {}
    if action == "resume":
        resume_dispatch = _resolve_resume_dispatch(
            conn,
            item_id=ctx.get("item_id"),
            epic_id=ctx.get("epic_id"),
            task_num=ctx.get("task_num"),
            status=ctx.get("status"),
        )
        adapter = resume_dispatch.get("adapter", adapter)
        dispatch_source = resume_dispatch.get("dispatch_source", "resume-status-mapping")
        if ctx.get("status"):
            dispatch_context["status"] = ctx["status"]

    emit_adapter_dispatch_chosen(
        session_id,
        project=project,
        action=action,
        item_id=selected_item,
        adapter=adapter,
        dispatch_source=dispatch_source,
        actual_lane=actual_lane,
        reasoning=reason,
        context=dispatch_context or None,
    )

__all__ = [
    "SessionError",
    "DEFAULT_STALE_THRESHOLD_MINUTES",
    "DEFAULT_PROGRESS_THRESHOLD_MINUTES",
    "EXECUTOR_STALE_TTL_OVERRIDES_MINUTES",
    "EVENT_HARNESS_SESSION_STARTED",
    "EVENT_HARNESS_SESSION_ENDED",
    "EVENT_WORK_CLAIMED",
    "EVENT_WORK_RELEASED",
    "EVENT_WORK_RECLAIMED",
    "EVENT_WORK_HANDED_OFF",
    "EVENT_CHAIN_STEP_COMPLETED",
    "EVENT_HARNESS_SESSION_HOOK_FAILED",
    "EVENT_HARNESS_SESSION_STALE_RECLAIMED",
    "EVENT_HARNESS_SESSION_END_REJECTED_ACTIVE_CLAIM",
    "EVENT_OPERATOR_CLAIM_OVERRIDE",
    "EVENT_RECLAIM_ABORTED",
    "EVENT_HARNESS_SESSION_STALE_SWEEP_COMPLETED",
    "EVENT_HARNESS_SESSION_END_RELEASED_CLAIMS",
    "EVENT_ITEM_CLAIM_RELEASE_FAILED",
    "EVENT_SESSION_REACTIVATED_WITH_RELEASED_CLAIMS",
    "_SESSION_EVENT_REGISTRY_ROWS",
    "ensure_session_event_registry_entries",
    "_emit_event",
    "_emit_session_event",
    "_NEXT_STEP_TO_PATH",
    "emit_next_action_chosen",
    "emit_drift_review_completed",
    "emit_lane_routing_decision",
    "emit_adapter_dispatch_chosen",
    "_resolve_resume_dispatch",
    "emit_post_decision_telemetry",
]
