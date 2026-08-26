"""Registered handler for the steering scope's automatic staffing backstop."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class BackstopEvaluateRequest(BaseModel):
    """Evaluate one steering scope and staff its unpicked runnable work."""

    executor_surface: Optional[str] = Field(
        default=None,
        description="Surface to staff on; defaults to the caller's own.",
    )
    model: Optional[str] = None
    dry_run: bool = False


class BackstopEvaluateResponse(BaseModel):
    project_id: int
    steering_claim_id: int
    evaluated_at: str
    dry_run: bool
    unpicked_after_seconds: int
    worker_budget: int
    workers_in_flight: int
    headroom: int
    staff: List[Dict[str, Any]] = Field(default_factory=list)
    withheld: List[Dict[str, Any]] = Field(default_factory=list)
    launched: List[Dict[str, Any]] = Field(default_factory=list)
    refused: List[Dict[str, Any]] = Field(default_factory=list)


def _error(code: str, message: str, jsonpath: str = "$.payload") -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _authorized_project_id(request: FunctionCallRequest) -> int | None:
    raw = (request.options or {}).get("authorized_project_id")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _caller_surface(conn: Any, session_id: str) -> str | None:
    from yoke_core.domain.session_launch_store import marker, value

    row = conn.execute(
        f"SELECT executor_surface FROM harness_sessions WHERE session_id = {marker(conn)}",
        (session_id,),
    ).fetchone()
    return str(value(row, "executor_surface", 0) or "") or None if row else None


def handle_evaluate(request: FunctionCallRequest) -> HandlerOutcome:
    """Staff the scope's unpicked work, or explain why nothing was staffed."""
    try:
        body = BackstopEvaluateRequest.model_validate(request.payload or {})
    except ValidationError as exc:
        return _error("payload_invalid", f"evaluate payload invalid: {exc}")
    project_id = _authorized_project_id(request)
    if project_id is None:
        return _error(
            "project_context_required",
            "steering backstop evaluate requires --project <slug-or-id>",
            "$.target.project_id",
        )
    session_id = request.actor.session_id
    if not session_id:
        return _error(
            "actor_required",
            "the steering backstop runs as the steering claim holder",
            "$.actor.session_id",
        )

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.handlers.session_launch import _authorization, _fleet_policy
    from yoke_core.domain.project_settings import get_project_int_for_id
    from yoke_core.domain.session_launch_types import SessionLaunchError
    from yoke_core.domain.steering_launch_backstop import run_backstop

    conn = connect()
    try:
        surface = body.executor_surface or _caller_surface(conn, session_id)
        if not surface:
            return _error(
                "surface_required",
                "no executor surface to staff on: pass --executor-surface",
            )
        result = run_backstop(
            conn,
            session_id=session_id,
            project_id=project_id,
            auth=_authorization(conn, request, project_id),
            executor_surface=surface,
            unpicked_after_seconds=60
            * get_project_int_for_id(project_id, "steering_backstop_unpicked_minutes"),
            worker_budget=get_project_int_for_id(
                project_id, "steering_backstop_worker_budget"
            ),
            model=body.model,
            deadline_seconds=int(
                _fleet_policy(conn, project_id, "fleet.launch_deadline_minutes")
            )
            * 60,
            max_body_bytes=int(_fleet_policy(conn, project_id, "fleet.max_body_bytes")),
            surface_fallback_enabled=bool(
                _fleet_policy(conn, project_id, "fleet.surface_fallback")
            ),
            auto_select_machine=bool(
                _fleet_policy(conn, project_id, "fleet.auto_select_machine")
            ),
            dry_run=body.dry_run,
        )
    except SessionLaunchError as exc:
        return _error(exc.code, str(exc))
    except LookupError as exc:
        return _error("not_found", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(result_payload=result)


__all__ = [
    "BackstopEvaluateRequest",
    "BackstopEvaluateResponse",
    "handle_evaluate",
]
