"""Registered deployment-run terminalization function."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.deployment_common import error, run_id


class DeploymentRunTerminalizeRequest(BaseModel):
    disposition: str
    reason: str
    run_id: Optional[str] = None


class DeploymentRunTerminalizeResponse(BaseModel):
    run_id: str
    project: str
    prior_status: str
    final_status: str
    reason: str
    terminalized_at: str
    terminalized_by_actor_id: Optional[int]
    terminalized_by_session_id: str
    event_id: str


def handle_deployment_run_terminalize(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    resolved_run_id = run_id(request, "deployment_runs.terminalize")
    if isinstance(resolved_run_id, HandlerOutcome):
        return resolved_run_id
    payload = request.payload or {}
    disposition = payload.get("disposition")
    reason = payload.get("reason")
    if not isinstance(disposition, str):
        return error(
            "payload_invalid",
            "disposition must be one of: cancelled, failed",
            jsonpath="$.payload.disposition",
        )
    if not isinstance(reason, str) or not reason.strip():
        return error(
            "payload_invalid",
            "reason must be a non-empty string",
            jsonpath="$.payload.reason",
        )
    if len(reason) > 2000:
        return error(
            "payload_invalid",
            "reason must be at most 2000 characters",
            jsonpath="$.payload.reason",
        )
    raw_actor_id = request.actor.actor_id
    actor_id = int(raw_actor_id) if str(raw_actor_id or "").isdigit() else None

    from yoke_core.domain.deployment_run_terminalization import (
        RunTerminalizationRejected,
        terminalize_run,
    )

    try:
        result = terminalize_run(
            resolved_run_id,
            disposition=disposition,
            reason=reason,
            actor_id=actor_id,
            session_id=request.actor.session_id,
        )
    except LookupError as exc:
        return error("not_found", str(exc), jsonpath="$.target.workflow_run_id")
    except RunTerminalizationRejected as exc:
        return error("invalid_state", str(exc))
    return HandlerOutcome(
        result_payload={
            "run_id": result.run_id,
            "project": result.project,
            "prior_status": result.prior_status,
            "final_status": result.final_status,
            "reason": result.reason,
            "terminalized_at": result.terminalized_at,
            "terminalized_by_actor_id": result.terminalized_by_actor_id,
            "terminalized_by_session_id": result.terminalized_by_session_id,
            "event_id": result.event_id,
        },
        primary_success=True,
    )


__all__ = [
    "DeploymentRunTerminalizeRequest",
    "DeploymentRunTerminalizeResponse",
    "handle_deployment_run_terminalize",
]
