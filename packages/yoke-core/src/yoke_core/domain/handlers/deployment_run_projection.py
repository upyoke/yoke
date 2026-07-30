"""Registered deployment-run snapshot projection handler."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome

from yoke_core.domain.handlers.deployment_common import error, require_global


class DeploymentRunProjectSnapshotRequest(BaseModel):
    snapshot: Dict[str, Any]
    expected_destination_digest: Optional[str] = None


class DeploymentRunProjectSnapshotResponse(BaseModel):
    run_id: str
    outcome: str
    snapshot_digest: str
    changed_fields: List[str]


def handle_project_snapshot(request: FunctionCallRequest) -> HandlerOutcome:
    """Project a source-authoritative canonical run into this tenant DB."""
    invalid = require_global(request, "deployment_runs.project_snapshot")
    if invalid is not None:
        return invalid
    payload = request.payload or {}
    snapshot = payload.get("snapshot")
    expected = payload.get("expected_destination_digest")
    if not isinstance(snapshot, dict):
        return error(
            "payload_invalid",
            "snapshot must be an object",
            jsonpath="$.payload.snapshot",
        )
    if expected is not None and not isinstance(expected, str):
        return error(
            "payload_invalid",
            "expected_destination_digest must be a string when present",
            jsonpath="$.payload.expected_destination_digest",
        )
    from yoke_core.domain.deployment_run_projection import (
        DeploymentRunProjectionCollision,
        DeploymentRunProjectionError,
        project_snapshot,
    )

    try:
        result = project_snapshot(
            snapshot,
            expected_destination_digest=expected,
        )
    except DeploymentRunProjectionCollision as exc:
        return error(
            "deployment_run_projection_collision",
            str(exc),
            jsonpath="$.payload",
        )
    except (DeploymentRunProjectionError, LookupError) as exc:
        return error(
            "deployment_run_projection_rejected",
            str(exc),
            jsonpath="$.payload.snapshot",
        )
    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "DeploymentRunProjectSnapshotRequest",
    "DeploymentRunProjectSnapshotResponse",
    "handle_project_snapshot",
]
