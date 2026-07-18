"""Registered server-side managed-project artifact rendering."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.actor_permissions import PERM_ORG_ADMIN, PermissionDenied
from yoke_core.domain.actor_project_visibility import numeric_actor_id
from yoke_core.domain.control_plane_authority import (
    require_control_plane_permission,
)
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.project_artifact_bundle import (
    ProjectArtifactBundleError,
    build_project_artifact_bundle,
)
from yoke_core.domain.pydantic_validation_safety import safe_validation_message


class ProjectArtifactsRenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str
    source_dev_admin: bool = False


class RenderedArtifact(BaseModel):
    path: str
    content: str
    sha256: str
    mode: int


class ProjectArtifactsRenderResponse(BaseModel):
    bundle_schema: int
    project_id: int
    project_slug: str
    applicable: bool
    applicability_reason: str
    template: str
    template_version: str
    yoke_version: str
    template_source: str
    template_digest: str
    settings_digest: str
    content_digest: str
    checkout_identity: dict[str, Any]
    artifact_policy: dict[str, Any]
    artifacts: list[RenderedArtifact]
    pulumi_stack_config: dict[str, Any]


def handle_projects_artifacts_render(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        parsed = ProjectArtifactsRenderRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _failure("payload_invalid", safe_validation_message(exc), "$.payload")
    conn = connect()
    try:
        if parsed.source_dev_admin:
            actor_id = numeric_actor_id(request.actor.actor_id)
            if actor_id is None:
                return _failure(
                    "permission_denied",
                    "source-dev/admin artifact rendering requires an explicit "
                    "authenticated actor with org-admin authority",
                    "$.payload.source_dev_admin",
                )
            try:
                require_control_plane_permission(
                    conn,
                    actor_id=actor_id,
                    permission_key=PERM_ORG_ADMIN,
                )
            except PermissionDenied as exc:
                return _failure(
                    "permission_denied",
                    str(exc),
                    "$.payload.source_dev_admin",
                )
        result = build_project_artifact_bundle(
            conn,
            parsed.project,
            source_dev_admin=parsed.source_dev_admin,
        )
    except LookupError as exc:
        return _failure("not_found", str(exc), "$.payload.project")
    except (ProjectArtifactBundleError, ValueError) as exc:
        return _failure("artifact_render_failed", str(exc), "$.payload")
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)


def _failure(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


__all__ = [
    "ProjectArtifactsRenderRequest",
    "ProjectArtifactsRenderResponse",
    "RenderedArtifact",
    "handle_projects_artifacts_render",
]
