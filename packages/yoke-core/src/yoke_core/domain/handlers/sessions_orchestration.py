"""Registered session/orchestration wrappers for taught service-client paths."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

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


class TouchResponse(BaseModel):
    success: bool
    session: Dict[str, Any]


class CheckpointRequest(BaseModel):
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


class OwnershipGuardRequest(BaseModel):
    pass


class OwnershipGuardResponse(BaseModel):
    owned: bool
    holder_session_id: Optional[str] = None
    claim_id: Optional[int] = None
    defense_in_flight: bool


class OfferRequest(BaseModel):
    executor: str
    provider: str
    workspace: str
    model: Optional[str] = None
    lane: Optional[str] = None
    step: int = 1
    supported_paths: List[str] = Field(default_factory=list)
    project: Optional[str] = None


class OfferResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    action: str
    reason: str
    chainable: bool = False
    correlation_id: str
    context: Optional[Dict[str, Any]] = None


def _err(
    code: str, message: str, *, jsonpath: Optional[str] = None,
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
            session = heartbeat(conn, sid)
            if body.mode is not None:
                set_session_mode(conn, sid, body.mode)
                session["mode"] = body.mode
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


def handle_ownership_guard(request: FunctionCallRequest) -> HandlerOutcome:
    sid = _session_id(request)
    if not sid:
        return _err("session_required", "session id is required")
    item_id = request.target.item_id
    if item_id is None:
        return _err(
            "target_invalid",
            "sessions.ownership_guard requires an item target",
            jsonpath="$.target.item_id",
        )

    from yoke_core.domain.sessions_offer_ownership_guard import (
        evaluate_ownership_guard,
    )

    with _connect_rw() as conn:
        result = evaluate_ownership_guard(
            conn, session_id=sid, item_id=int(item_id),
        )
    return HandlerOutcome(result_payload=asdict(result))


def handle_offer(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = OfferRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _err("payload_invalid", f"offer payload invalid: {exc}")
    from yoke_core.api.service_client_sessions_offer import (
        SessionOfferCommandError,
        run_session_offer,
    )

    try:
        result = run_session_offer(
            executor=body.executor,
            provider=body.provider,
            model=body.model,
            workspace=body.workspace,
            lane=body.lane,
            session_id=_session_id(request) or None,
            step=body.step,
            supported_paths=body.supported_paths,
            project=body.project,
        )
    except SessionOfferCommandError as exc:
        return _err("session_offer_failed", str(exc))
    return HandlerOutcome(result_payload=result)


__all__ = [
    "TouchRequest", "TouchResponse", "handle_touch",
    "CheckpointRequest", "CheckpointResponse", "handle_checkpoint",
    "CheckpointReadRequest", "handle_checkpoint_read",
    "OwnershipGuardRequest", "OwnershipGuardResponse", "handle_ownership_guard",
    "OfferRequest", "OfferResponse", "handle_offer",
    "ChargeScheduleRequest", "ChargeScheduleResponse", "handle_charge_schedule",
]
