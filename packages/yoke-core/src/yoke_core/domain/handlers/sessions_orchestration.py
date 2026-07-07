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


class ChargeScheduleRequest(BaseModel):
    project: Optional[str] = None
    wip_cap: Optional[int] = None


class ChargeScheduleResponse(BaseModel):
    project_scope: List[int]
    sml_state: Dict[str, Any]
    selected_step: Optional[Dict[str, Any]] = None
    ranked_steps: List[Dict[str, Any]]
    blocked_steps: List[Dict[str, Any]]
    exceptional_steps: List[Dict[str, Any]]
    wip_cap: int
    wip_active: int
    conduct_eligible: List[Dict[str, Any]]
    frozen_steps: List[Dict[str, Any]]


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

    with _connect_rw() as conn:
        try:
            checkpoint = update_chain_checkpoint(
                conn,
                sid,
                step=body.step,
                action=body.action,
                chainable=body.chainable,
                handler_outcome=body.outcome,
                item_id=body.item_id,
                task_num=body.task_num,
                status=body.status,
                required_path=body.required_path,
                pre_status=body.pre_status,
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


def _resolve_default_wip_cap(project_scope: List[int]) -> int:
    from yoke_core.domain.project_settings import get_project_int_for_id

    project_id = project_scope[0] if len(project_scope) == 1 else None
    return get_project_int_for_id(project_id, "wip_cap")


def _scheduled_step_to_dict(step: Any) -> Dict[str, Any]:
    return {
        "item_id": step.item_id,
        "item_type": step.item_type,
        "status": step.status,
        "title": step.title,
        "priority": step.priority,
        "next_step": (
            step.next_step.value
            if hasattr(step.next_step, "value")
            else str(step.next_step)
        ),
        "rank": step.rank,
        "claim_state": (
            step.claim_state.value
            if hasattr(step.claim_state, "value")
            else str(step.claim_state)
        ),
        "gate_evaluations": [
            {
                "blocking_item": ge.blocking_item,
                "relation": ge.relation,
                "gate_point": ge.gate_point,
                "satisfaction": ge.satisfaction,
                "satisfied": ge.satisfied,
                "reason": ge.reason,
                "rationale": getattr(ge, "rationale", ""),
            }
            for ge in step.gate_evaluations
        ],
        "explanation": step.explanation,
        "adapter": step.adapter,
        "blocked_by": step.blocked_by,
        "blocked_reasons": step.blocked_reasons,
        "unblocks_count": step.unblocks_count,
        "downstream_depth": step.downstream_depth,
        "created_at": step.created_at,
    }


def _scheduler_result_to_dict(result: Any) -> Dict[str, Any]:
    return {
        "project_scope": list(result.project_scope),
        "sml_state": {"coherent": result.sml_state.coherent},
        "selected_step": (
            _scheduled_step_to_dict(result.selected_step)
            if result.selected_step
            else None
        ),
        "ranked_steps": [_scheduled_step_to_dict(s) for s in result.ranked_steps],
        "blocked_steps": [_scheduled_step_to_dict(s) for s in result.blocked_steps],
        "exceptional_steps": [
            _scheduled_step_to_dict(s) for s in result.exceptional_steps
        ],
        "wip_cap": result.wip_cap,
        "wip_active": result.wip_active,
        "conduct_eligible": [
            _scheduled_step_to_dict(s) for s in result.conduct_eligible
        ],
        "frozen_steps": [_scheduled_step_to_dict(s) for s in result.frozen_steps],
    }


def handle_charge_schedule(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = ChargeScheduleRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _err("payload_invalid", f"charge schedule payload invalid: {exc}")
    if body.wip_cap is not None and not 1 <= body.wip_cap <= 100:
        return _err("payload_invalid", "wip_cap must be between 1 and 100")

    from yoke_core.domain.scheduler import compute_schedule
    from yoke_core.domain.session_project_scope import (
        parse_project_cli_arg,
        resolve_session_project_scope,
    )

    with _connect_rw() as conn:
        try:
            project_scope = resolve_session_project_scope(
                conn, override=parse_project_cli_arg(body.project),
            )
        except ValueError as exc:
            return _err("project_scope_invalid", str(exc))
        wip_cap = body.wip_cap
        if wip_cap is None:
            wip_cap = _resolve_default_wip_cap(project_scope)
        result = compute_schedule(conn, project_scope=project_scope, wip_cap=wip_cap)
    return HandlerOutcome(result_payload=_scheduler_result_to_dict(result))


__all__ = [
    "TouchRequest", "TouchResponse", "handle_touch",
    "CheckpointRequest", "CheckpointResponse", "handle_checkpoint",
    "CheckpointReadRequest", "handle_checkpoint_read",
    "OwnershipGuardRequest", "OwnershipGuardResponse", "handle_ownership_guard",
    "OfferRequest", "OfferResponse", "handle_offer",
    "ChargeScheduleRequest", "ChargeScheduleResponse", "handle_charge_schedule",
]
