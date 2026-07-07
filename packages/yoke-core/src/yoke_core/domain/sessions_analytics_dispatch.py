"""Session decision and dispatch telemetry emitters."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from . import db_backend
from .sessions_analytics_core import _NEXT_STEP_TO_PATH, _emit_event

logger = logging.getLogger(__name__)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def emit_next_action_chosen(
    session_id: str,
    action: str,
    reason: str,
    correlation_id: str,
    *,
    project: str = "yoke",
    chainable: bool = False,
    step: int = 1,
    supported_paths: Optional[List[str]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit canonical NextActionChosen event.

    Called by CLI and API adapters after ``decide_next_action`` returns,
    so that event emission is centralized rather than duplicated in each
    adapter.
    """
    event_ctx: Dict[str, Any] = {
        "session_id": session_id,
        "action": action,
        "reason": reason,
        "chainable": chainable,
        "correlation_id": correlation_id,
        "step": step,
    }
    if supported_paths:
        event_ctx["supported_paths"] = supported_paths
    # Merge action-specific context (includes required_path on escalate)
    if context:
        event_ctx.update(context)

    item_id: Optional[str] = None
    task_num: Optional[int] = None
    if context:
        if action == "resume":
            item_id = context.get("item_id")
            task_num = context.get("task_num")
        elif action == "charge":
            item_id = context.get("selected_item")
            if context.get("task_num") is not None:
                task_num = context.get("task_num")

    _emit_event(
        "NextActionChosen",
        event_kind="workflow",
        event_type="session_directive",
        source_type="backend",
        session_id=session_id,
        project=project,
        item_id=item_id,
        task_num=task_num,
        context=event_ctx,
        severity="STATUS",  # never pruned — decision audit trail
    )


def emit_drift_review_completed(
    *,
    session_id: str,
    project: str,
    project_scope: Optional[List[str]] = None,
    classification: str,
    summary: str,
    checkpoint_start: str,
    reviewed_through: str,
    delivered_items: Optional[List[str]] = None,
) -> None:
    """Emit DriftReviewCompleted checkpoint event.

    This event marks that the delivered delta through *reviewed_through*
    has been assessed.  Its ``created_at`` timestamp becomes the new
    checkpoint anchor for subsequent drift-review windows.
    """
    event_ctx: Dict[str, Any] = {
        "project": project,
        "classification": classification,
        "summary": summary,
        "checkpoint_start": checkpoint_start,
        "reviewed_through": reviewed_through,
        "delivered_items": delivered_items or [],
    }
    if project_scope is not None:
        event_ctx["project_scope"] = list(project_scope)
    _emit_event(
        "DriftReviewCompleted",
        event_kind="lifecycle",
        event_type="drift_review",
        source_type="backend",
        session_id=session_id,
        context=event_ctx,
        severity="STATUS",
    )


def emit_lane_routing_decision(
    session_id: str,
    *,
    project: str = "yoke",
    actual_lane: str,
    selected_item: Optional[str] = None,
    next_step: Optional[str] = None,
    decision: str = "allowed",
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit LaneRoutingDecision from the shared post-decision path.

    Covers the verified routing outcomes:
    - allowed: the current lane is allowed to run the selected downstream path
    - blocked_policy: the current lane is not allowed to run the selected downstream path

    Called by both CLI and HTTP session-offer adapters.
    """
    event_ctx: Dict[str, Any] = {
        "actual_lane": actual_lane,
        "decision": decision,
    }
    if selected_item:
        event_ctx["selected_item"] = selected_item
    if next_step:
        event_ctx["next_step"] = next_step
    if context:
        event_ctx.update(context)

    _emit_event(
        "LaneRoutingDecision",
        event_kind="workflow",
        event_type="lane_routing",
        source_type="backend",
        session_id=session_id,
        project=project,
        item_id=selected_item,
        context=event_ctx,
    )


def emit_adapter_dispatch_chosen(
    session_id: str,
    *,
    project: str = "yoke",
    action: str,
    item_id: Optional[str] = None,
    adapter: Optional[str] = None,
    dispatch_source: Optional[str] = None,
    actual_lane: Optional[str] = None,
    reasoning: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit AdapterDispatchChosen from the shared post-decision path.

    Only emits for dispatchable actions (charge, resume).
    Does NOT emit for wait, escalate, or no_work.

    Called by both CLI and HTTP session-offer adapters.
    """
    if action not in ("charge", "resume"):
        return

    event_ctx: Dict[str, Any] = {
        "action": action,
        "adapter": adapter or "",
        "dispatch_source": dispatch_source or "",
    }
    if actual_lane:
        event_ctx["actual_lane"] = actual_lane
    if reasoning:
        event_ctx["reasoning"] = reasoning
    if context:
        event_ctx.update(context)

    _emit_event(
        "AdapterDispatchChosen",
        event_kind="workflow",
        event_type="adapter_dispatch",
        source_type="backend",
        session_id=session_id,
        project=project,
        item_id=item_id,
        context=event_ctx,
    )


def _resolve_resume_dispatch(
    conn: Any,
    *,
    item_id: Optional[str],
    epic_id: Optional[int],
    task_num: Optional[int],
    status: Optional[str],
) -> Dict[str, str]:
    """Resolve the downstream path for a resume directive from current item state."""
    if epic_id is not None and task_num is not None and not item_id:
        return {
            "adapter": "conduct",
            "dispatch_source": "resume-status-mapping",
        }

    resolved_type = "issue"
    resolved_status = status or ""
    if item_id:
        try:
            item_num = int(str(item_id).replace("YOK-", ""))
        except ValueError:
            item_num = None
        if item_num is not None:
            p = _p(conn)
            row = conn.execute(
                f"SELECT type, status FROM items WHERE id = {p}",
                (item_num,),
            ).fetchone()
            if row is not None:
                resolved_type = row["type"] or resolved_type
                resolved_status = row["status"] or resolved_status

    if not resolved_status:
        return {"dispatch_source": "resume-status-mapping"}

    try:
        from .frontier import classify_next_action
        from .scheduler import _compute_next_step

        adapter = classify_next_action(resolved_status, item_type=resolved_type)
        step = _compute_next_step(resolved_type, resolved_status, adapter)
        return {
            "adapter": _NEXT_STEP_TO_PATH.get(step.next_step.value, step.next_step.value),
            "dispatch_source": "resume-status-mapping",
        }
    except Exception as exc:
        logger.debug("Failed to resolve resume dispatch for %s: %s", item_id, exc)
        return {"dispatch_source": "resume-status-mapping"}
