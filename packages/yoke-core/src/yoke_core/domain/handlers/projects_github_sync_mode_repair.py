"""Handler for unsafe sync-mode and unbound-projection repair."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ProjectsGithubSyncModeRepairRequest(BaseModel):
    project: Optional[str] = None
    apply: bool = False


class ProjectsGithubSyncModeRepairResponse(BaseModel):
    applied: bool
    matched: int
    normalized: int
    projects: List[Dict[str, Any]]


def handle_projects_github_sync_mode_repair(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        parsed = ProjectsGithubSyncModeRepairRequest(**(request.payload or {}))
    except ValidationError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=str(exc),
                jsonpath="$.payload",
            ),
        )
    from yoke_core.domain.projects_github_sync_mode_repair import (
        cmd_repair_unbound_enabled_sync_modes,
    )

    try:
        result = cmd_repair_unbound_enabled_sync_modes(**parsed.dict())
    except (LookupError, ValueError) as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=str(exc),
                jsonpath="$.payload.project",
            ),
        )
    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "ProjectsGithubSyncModeRepairRequest",
    "ProjectsGithubSyncModeRepairResponse",
    "handle_projects_github_sync_mode_repair",
]
