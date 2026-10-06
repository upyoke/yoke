"""Session analytics public import front door."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .sessions_analytics_core import (
    DEFAULT_PROGRESS_THRESHOLD_MINUTES,
    DEFAULT_STALE_THRESHOLD_MINUTES,
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


__all__ = [
    "SessionError",
    "DEFAULT_STALE_THRESHOLD_MINUTES",
    "DEFAULT_PROGRESS_THRESHOLD_MINUTES",
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
]
