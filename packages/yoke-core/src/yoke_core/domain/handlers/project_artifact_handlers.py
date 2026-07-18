"""Client-local function wrapper for artifact reconciliation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.pydantic_validation_safety import safe_validation_message
from yoke_cli.project_artifacts import ProjectArtifactError, refresh


class ProjectArtifactRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo_root: str | None = None
    project: str
    apply: bool = False
    verify: bool = False
    source_dev_admin: bool = False


class ProjectArtifactRefreshResponse(BaseModel):
    operation: str
    project_id: int
    project_slug: str
    applicable: bool
    applicability_reason: str
    repo_root: str
    template: str
    template_version: str
    yoke_version: str
    template_source: str
    template_digest: str
    settings_digest: str
    content_digest: str
    checkout_identity: dict[str, Any]
    artifact_policy: dict[str, Any]
    manifest: str
    plan: dict[str, Any]
    drift: bool
    conflict_count: int
    applied: bool
    refused: bool
    skipped: bool = False
    pulumi_stack_config: dict[str, Any]
    refusal_reason: str | None = None
    apply_result: dict[str, Any] | None = None


def handle_project_artifact_refresh(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        parsed = ProjectArtifactRefreshRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _failure("payload_invalid", safe_validation_message(exc))
    try:
        result = refresh(
            parsed.repo_root,
            project=parsed.project,
            apply=parsed.apply,
            verify=parsed.verify,
            source_dev_admin=parsed.source_dev_admin,
            session_id=request.actor.session_id,
        )
    except ProjectArtifactError as exc:
        return _failure("project_artifact_refresh_failed", str(exc))
    return HandlerOutcome(primary_success=True, result_payload=result)


def _failure(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


__all__ = [
    "ProjectArtifactRefreshRequest",
    "ProjectArtifactRefreshResponse",
    "handle_project_artifact_refresh",
]
