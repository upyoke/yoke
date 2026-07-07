"""``projects.create`` / ``projects.update`` handlers for project onboarding.

Both are backed by the idempotent ``cmd_upsert`` workhorse; they differ only
in the authorization-relevant ``mode`` (org-scoped register vs project-scoped
edit — see ``function_authz_scope``). The shared request/response models keep
the payload shape identical across the two surfaces.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ProjectsUpsertRequest(BaseModel):
    slug: str
    name: str
    org: Optional[str] = None
    project_id: Optional[int] = None
    default_branch: Optional[str] = None
    github_repo: Optional[str] = None
    public_item_prefix: Optional[str] = None
    emoji: Optional[str] = None
    github_sync_mode: Optional[str] = None


class ProjectsUpsertResponse(BaseModel):
    created: bool
    project: Dict[str, Any]


def _handle_projects_write(request: FunctionCallRequest, *, mode: str) -> HandlerOutcome:
    payload = request.payload or {}
    try:
        parsed = ProjectsUpsertRequest(**payload)
    except ValidationError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=str(exc),
                jsonpath="$.payload",
            ),
        )

    from yoke_core.domain.projects_upsert import cmd_upsert

    try:
        data = parsed.dict()
        if mode == "update" and data.get("project_id") is None:
            authorized_id = (request.options or {}).get("authorized_project_id")
            if authorized_id is not None:
                data["project_id"] = int(authorized_id)
        result = cmd_upsert(mode=mode, **data)
    except ValueError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=str(exc),
                jsonpath="$.payload",
            ),
        )
    return HandlerOutcome(result_payload=result, primary_success=True)


def handle_projects_create(request: FunctionCallRequest) -> HandlerOutcome:
    return _handle_projects_write(request, mode="create")


def handle_projects_update(request: FunctionCallRequest) -> HandlerOutcome:
    return _handle_projects_write(request, mode="update")


__all__ = [
    "ProjectsUpsertRequest",
    "ProjectsUpsertResponse",
    "handle_projects_create",
    "handle_projects_update",
]
