"""Registered ``charge.schedule`` handler — claim-aware frontier for /yoke charge."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ChargeScheduleRequest(BaseModel):
    project: Optional[str] = None
    wip_cap: Optional[int] = None
    item: Optional[str] = None
    workspace: Optional[str] = None


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
    runnable_elsewhere: List[Dict[str, Any]] = []
    workspace_home_project: Optional[str] = None


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def _resolve_default_wip_cap(project_scope: List[int]) -> int:
    from yoke_core.domain.project_settings import resolve_default_wip_cap

    return resolve_default_wip_cap(project_scope)


def _scheduled_step_to_dict(step: Any, conn: Any = None) -> Dict[str, Any]:
    from yoke_core.domain.sessions_queries_base import display_claim_item_id

    return {
        "item_id": display_claim_item_id(str(step.item_id), conn),
        "workflow_id": step.workflow_id,
        "workflow_version_id": step.workflow_version_id,
        "workflow_version": step.workflow_version,
        "status": step.status,
        "title": step.title,
        "priority": step.priority,
        "project": getattr(step, "project", ""),
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


def scheduler_result_to_dict(result: Any, conn: Any = None) -> Dict[str, Any]:
    return {
        "project_scope": list(result.project_scope),
        "sml_state": {"coherent": result.sml_state.coherent},
        "selected_step": (
            _scheduled_step_to_dict(result.selected_step, conn)
            if result.selected_step
            else None
        ),
        "ranked_steps": [_scheduled_step_to_dict(s, conn) for s in result.ranked_steps],
        "blocked_steps": [_scheduled_step_to_dict(s, conn) for s in result.blocked_steps],
        "exceptional_steps": [
            _scheduled_step_to_dict(s, conn) for s in result.exceptional_steps
        ],
        "wip_cap": result.wip_cap,
        "wip_active": result.wip_active,
        "conduct_eligible": [
            _scheduled_step_to_dict(s, conn) for s in result.conduct_eligible
        ],
        "frozen_steps": [_scheduled_step_to_dict(s, conn) for s in result.frozen_steps],
        "runnable_elsewhere": list(getattr(result, "runnable_elsewhere", None) or []),
        "workspace_home_project": getattr(result, "workspace_home_project", None),
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
    from yoke_core.domain.session_workspace_frontier import (
        apply_workspace_home_filter,
        enrich_elsewhere_checkout_paths,
        resolve_offer_home_project,
        workspace_home_filter_requested,
    )

    override = parse_project_cli_arg(body.project)
    session_id = request.actor.session_id or ""
    with _connect_rw() as conn:
        try:
            project_scope = resolve_session_project_scope(conn, override=override)
        except ValueError as exc:
            return _err("project_scope_invalid", str(exc))
        wip_cap = body.wip_cap
        if wip_cap is None:
            wip_cap = _resolve_default_wip_cap(project_scope)
        result = compute_schedule(
            conn, project_scope=project_scope, wip_cap=wip_cap,
            session_id=session_id or None,
        )
        if workspace_home_filter_requested(project_override=override, item=body.item):
            home = resolve_offer_home_project(
                conn,
                workspace=body.workspace or "",
                session_id=session_id or None,
            )
            result = apply_workspace_home_filter(
                result, home_project_id=home, conn=conn,
            )
        payload = enrich_elsewhere_checkout_paths(
            scheduler_result_to_dict(result, conn)
        )
    return HandlerOutcome(result_payload=payload)


__all__ = [
    "ChargeScheduleRequest",
    "ChargeScheduleResponse",
    "handle_charge_schedule",
    "scheduler_result_to_dict",
]
