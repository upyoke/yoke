"""Registered session/orchestration wrappers for taught service-client paths."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.handlers.sessions_charge_schedule import (
    ChargeScheduleRequest,
    ChargeScheduleResponse,
    handle_charge_schedule,
)


class TouchRequest(BaseModel):
    mode: Optional[str] = None
    reason: Optional[str] = None


class TouchResponse(BaseModel):
    success: bool
    session: Dict[str, Any]


class CheckpointRequest(BaseModel):
    # A wire public ref resolves onto this engine key as an int.
    model_config = ConfigDict(coerce_numbers_to_str=True)

    step: int
    action: str
    chainable: bool
    item_id: Optional[str] = None
    task_num: Optional[int] = None
    outcome: str = "completed"
    status: Optional[str] = None
    required_path: Optional[str] = None
    pre_status: Optional[str] = None
    failure_class: Optional[str] = None


class CheckpointResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    step: Optional[int] = None
    action: Optional[str] = None
    chainable: Optional[bool] = None
    handler_outcome: Optional[str] = None
    completed_at: Optional[str] = None


class CheckpointReadRequest(BaseModel):
    pass


def _err(
    code: str,
    message: str,
    *,
    jsonpath: Optional[str] = None,
) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def _session_id(request: FunctionCallRequest) -> str:
    return request.actor.session_id or ""


def handle_touch(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = TouchRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _err("payload_invalid", f"touch payload invalid: {exc}")
    sid = _session_id(request)
    if not sid:
        return _err("session_required", "session id is required")

    from yoke_core.domain.sessions import SessionError, heartbeat, set_session_mode

    with _connect_rw() as conn:
        try:
            session = heartbeat(
                conn, sid, reason=body.reason if body.mode is None else None
            )
            if body.mode is not None:
                session = set_session_mode(conn, sid, body.mode, reason=body.reason)
        except SessionError as exc:
            return _err(exc.code.lower(), exc.message)
    return HandlerOutcome(result_payload={"success": True, "session": session})


def handle_checkpoint(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = CheckpointRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _err("payload_invalid", f"checkpoint payload invalid: {exc}")
    sid = _session_id(request)
    if not sid:
        return _err("session_required", "session id is required")

    from yoke_core.domain.sessions import SessionError, update_chain_checkpoint
    from yoke_core.domain.sessions_handler_outcome import (
        render_chain_summary_label,
        resolve_checkpoint_outcome,
        resolved_checkpoint_chainable,
    )

    outcome = resolve_checkpoint_outcome(
        outcome=body.outcome,
        failure_class=body.failure_class,
        required_path=body.required_path,
        pre_status=body.pre_status,
        post_status=body.status,
    )
    chainable = resolved_checkpoint_chainable(body.chainable, outcome)
    label = render_chain_summary_label(outcome)

    with _connect_rw() as conn:
        try:
            checkpoint = update_chain_checkpoint(
                conn,
                sid,
                step=body.step,
                action=body.action,
                chainable=chainable,
                handler_outcome=outcome,
                item_id=body.item_id,
                task_num=body.task_num,
                status=body.status,
                required_path=body.required_path,
                pre_status=body.pre_status,
                chain_summary_label=label,
            )
        except SessionError as exc:
            return _err(exc.code.lower(), exc.message)
    return HandlerOutcome(result_payload=checkpoint)


def handle_checkpoint_read(request: FunctionCallRequest) -> HandlerOutcome:
    sid = _session_id(request)
    if not sid:
        return _err("session_required", "session id is required")

    from yoke_core.domain.sessions import read_chain_checkpoint

    with _connect_rw() as conn:
        checkpoint = read_chain_checkpoint(conn, sid) or {}
    return HandlerOutcome(result_payload=checkpoint)


__all__ = [
    "TouchRequest",
    "TouchResponse",
    "handle_touch",
    "CheckpointRequest",
    "CheckpointResponse",
    "handle_checkpoint",
    "CheckpointReadRequest",
    "handle_checkpoint_read",
    "ChargeScheduleRequest",
    "ChargeScheduleResponse",
    "handle_charge_schedule",
]
