"""Registered handler for the steering fleet report on demand.

The report normally arrives on its own — appended to the messages a steering
session already receives. This is the pull form. Omit a project to compose
every live steering claim this session holds; pass one to keep a single scope.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class SteeringReportGetRequest(BaseModel):
    """Read the fleet report for the scopes this caller steers."""


class SteeringReportGetResponse(BaseModel):
    composed_at: str = ""
    staffing_after_seconds: int = 0
    idle_after_seconds: int = 0
    actionable: bool = False
    fingerprint: str = ""
    body: str = ""
    project_id: Optional[int] = None
    available: List[Dict[str, Any]] = Field(default_factory=list)
    waited_too_long: List[Dict[str, Any]] = Field(default_factory=list)
    holders: List[Dict[str, Any]] = Field(default_factory=list)
    idle: List[Dict[str, Any]] = Field(default_factory=list)
    starved: List[Dict[str, Any]] = Field(default_factory=list)
    unregistered_launches: List[Dict[str, Any]] = Field(default_factory=list)
    landed_open: List[Dict[str, Any]] = Field(default_factory=list)
    landings: List[Dict[str, Any]] = Field(default_factory=list)
    landings_needing_action: List[Dict[str, Any]] = Field(default_factory=list)
    dead_waits: List[Dict[str, Any]] = Field(default_factory=list)
    launchable: List[Dict[str, Any]] = Field(default_factory=list)
    scopes: List[Dict[str, Any]] = Field(default_factory=list)


def _error(code: str, message: str, jsonpath: str = "$.payload") -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _requested_project_ref(request: FunctionCallRequest) -> Any:
    raw = (request.options or {}).get("authorized_project_id")
    if raw is not None:
        return raw
    target = request.target
    if target is not None and target.project_id not in (None, ""):
        return target.project_id
    payload = request.payload or {}
    return payload.get("project_id") or payload.get("project")


def _claim_required(project_id: int | None) -> HandlerOutcome:
    project = "P" if project_id is None else str(project_id)
    hint = f"--project {project} [--doc SLUG]"
    return _error(
        "steering_claim_required",
        "the fleet report reads from the live steering claim holder; "
        f"acquire it with `yoke claims steering acquire {hint}`",
        "$.actor.session_id",
    )


def handle_get(request: FunctionCallRequest) -> HandlerOutcome:
    """Compose held-scope reports, or one scope when --project is set."""
    try:
        SteeringReportGetRequest.model_validate(request.payload or {})
    except ValidationError as exc:
        return _error("payload_invalid", f"report payload invalid: {exc}")
    session_id = request.actor.session_id
    if not session_id:
        return _error(
            "actor_required",
            "the steering report reads as the steering claim holder",
            "$.actor.session_id",
        )

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.project_identity import resolve_project_id
    from yoke_core.domain.session_launch_store import utc_now
    from yoke_core.domain.steering_fleet_report_compose import (
        combined_dict,
        compose_held_reports,
    )
    from yoke_core.domain.steering_fleet_report_projection import report_dict
    from yoke_core.domain.steering_fleet_report_render import report_body

    conn = connect()
    try:
        ref = _requested_project_ref(request)
        project_id: int | None = None
        if ref is not None:
            try:
                project_id = resolve_project_id(conn, ref)
            except LookupError as exc:
                return _error("not_found", str(exc))
        combined = compose_held_reports(
            conn,
            session_id=session_id,
            now=utc_now(),
            project_id=project_id,
        )
        if not combined.sections:
            return _claim_required(project_id)
        if project_id is not None:
            report = combined.sections[0].report
            return HandlerOutcome(
                result_payload={**report_dict(report), "body": report_body(report)}
            )
        return HandlerOutcome(result_payload=combined_dict(combined))
    finally:
        conn.close()


__all__ = [
    "SteeringReportGetRequest",
    "SteeringReportGetResponse",
    "handle_get",
]
