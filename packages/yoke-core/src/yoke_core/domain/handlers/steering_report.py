"""Registered handler for reading one steering scope's fleet report on demand.

The report normally arrives on its own — appended to the messages a steering
session already receives. This is the pull form for a steerer who wants the
current picture between wakes, and it composes the identical report so the two
can never disagree.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.steering_claims import DEFAULT_STEERING_DOC_SLUG


class SteeringReportGetRequest(BaseModel):
    """Read the fleet report for the project this caller steers."""


class SteeringReportGetResponse(BaseModel):
    project_id: int
    composed_at: str
    staffing_after_seconds: int
    idle_after_seconds: int
    actionable: bool
    fingerprint: str
    available: List[Dict[str, Any]] = Field(default_factory=list)
    waited_too_long: List[Dict[str, Any]] = Field(default_factory=list)
    holders: List[Dict[str, Any]] = Field(default_factory=list)
    idle: List[Dict[str, Any]] = Field(default_factory=list)
    starved: List[Dict[str, Any]] = Field(default_factory=list)
    unregistered_launches: List[Dict[str, Any]] = Field(default_factory=list)
    landed_open: List[Dict[str, Any]] = Field(default_factory=list)
    dead_waits: List[Dict[str, Any]] = Field(default_factory=list)
    launchable: List[Dict[str, Any]] = Field(default_factory=list)
    body: str = ""


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


def handle_get(request: FunctionCallRequest) -> HandlerOutcome:
    """Compose this scope's report, or explain why the caller cannot read it."""
    try:
        SteeringReportGetRequest.model_validate(request.payload or {})
    except ValidationError as exc:
        return _error("payload_invalid", f"report payload invalid: {exc}")
    project_id = _authorized_project_id(request)
    if project_id is None:
        return _error(
            "project_context_required",
            "steering report get requires --project <slug-or-id>",
            "$.target.project_id",
        )
    session_id = request.actor.session_id
    if not session_id:
        return _error(
            "actor_required",
            "the steering report reads as the steering claim holder",
            "$.actor.session_id",
        )

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.project_settings import get_project_int_for_id
    from yoke_core.domain.steering_fleet_report import compose_report
    from yoke_core.domain.steering_claims import list_claims
    from yoke_core.domain.steering_fleet_report_render import (
        report_body,
        report_dict,
    )
    from yoke_core.domain.session_launch_store import utc_now

    conn = connect()
    try:
        claims = list_claims(
            conn,
            project_id=project_id,
            session_id=session_id,
            active_only=True,
        )
        if not claims:
            return _error(
                "steering_claim_required",
                "the fleet report reads from the live steering claim holder; "
                f"acquire it with `yoke claims steering acquire --project "
                f"{project_id} --doc {DEFAULT_STEERING_DOC_SLUG}`",
                "$.actor.session_id",
            )
        report = compose_report(
            conn,
            project_id=project_id,
            session_id=session_id,
            staffing_after_seconds=60
            * get_project_int_for_id(project_id, "steering_report_staffing_minutes"),
            idle_after_seconds=60
            * get_project_int_for_id(project_id, "steering_report_idle_minutes"),
            now=utc_now(),
        )
    except LookupError as exc:
        return _error("not_found", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={**report_dict(report), "body": report_body(report)}
    )


__all__ = [
    "SteeringReportGetRequest",
    "SteeringReportGetResponse",
    "handle_get",
]
