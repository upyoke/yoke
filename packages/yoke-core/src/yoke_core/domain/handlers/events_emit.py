"""Write-side handler for ``events.emit``."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class EventsEmitRequest(BaseModel):
    name: str
    kind: str
    type: str
    source_type: str
    severity: str = "INFO"
    outcome: Optional[str] = "completed"
    project: str = "yoke"
    item_id: Optional[str] = None
    task_num: Optional[int] = None
    org_id: Optional[str] = None
    environment: Optional[str] = None
    request_id: Optional[str] = None
    agent: Optional[str] = None
    tool_name: Optional[str] = None
    duration_ms: Optional[int] = None
    exit_code: Optional[int] = None
    trace_id: Optional[str] = None
    parent_id: Optional[str] = None
    anomaly_flags: Optional[str] = None
    tool_use_id: Optional[str] = None
    turn_id: Optional[str] = None
    hook_event_name: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)


class EventsEmitResponse(BaseModel):
    emitted: bool
    event_id: Optional[str]
    reason: str


def _bad_request(message: str, *, jsonpath: str = "$.payload") -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(
            code="payload_invalid",
            message=message,
            jsonpath=jsonpath,
        ),
    )


def handle_events_emit(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        payload = EventsEmitRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")

    from yoke_core.domain import events_crud
    from yoke_core.domain.events import emit_event
    from yoke_core.domain.events_retired_name_guard import RetiredEventNameError
    from yoke_core.domain.emit_event_parser import VALID_EVENT_KINDS

    if payload.kind not in VALID_EVENT_KINDS:
        return _bad_request(
            "kind must be one of: " + ", ".join(VALID_EVENT_KINDS),
            jsonpath="$.payload.kind",
        )
    if payload.source_type not in events_crud.VALID_SOURCE_TYPES:
        return _bad_request(
            "source_type must be one of: "
            + ", ".join(events_crud.VALID_SOURCE_TYPES),
            jsonpath="$.payload.source_type",
        )
    if payload.severity not in events_crud.VALID_SEVERITIES:
        return _bad_request(
            "severity must be one of: "
            + ", ".join(events_crud.VALID_SEVERITIES),
            jsonpath="$.payload.severity",
        )

    try:
        result = emit_event(
            payload.name,
            event_kind=payload.kind,
            event_type=payload.type,
            source_type=payload.source_type,
            session_id=request.actor.session_id or "",
            severity=payload.severity,
            outcome=payload.outcome,
            org_id=payload.org_id,
            environment=payload.environment,
            request_id=payload.request_id,
            project=payload.project,
            item_id=payload.item_id,
            task_num=payload.task_num,
            agent=payload.agent,
            tool_name=payload.tool_name,
            duration_ms=payload.duration_ms,
            exit_code=payload.exit_code,
            trace_id=payload.trace_id,
            parent_id=payload.parent_id,
            anomaly_flags=payload.anomaly_flags,
            tool_use_id=payload.tool_use_id,
            turn_id=payload.turn_id,
            hook_event_name=payload.hook_event_name,
            context=payload.context,
        )
    except RetiredEventNameError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="retired_event_name",
                message=str(exc),
                jsonpath="$.payload.name",
            ),
        )

    return HandlerOutcome(
        result_payload=EventsEmitResponse(
            emitted=bool(result.ok),
            event_id=result.event_id,
            reason=result.reason,
        ).model_dump(),
        primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "events.emit",
        "handler": handle_events_emit,
        "request_model": EventsEmitRequest,
        "response_model": EventsEmitResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.events_emit",
        "target_kinds": ["global"],
        "side_effects": ["event_emit"],
        "emitted_event_names": ["<payload.name>"],
        "guardrails": ["registered_event_name_guard"],
        "adapter_status": "live",
        "claim_required_kind": None,
    },
]


__all__ = [
    "EventsEmitRequest",
    "EventsEmitResponse",
    "REGISTRATIONS",
    "handle_events_emit",
]
