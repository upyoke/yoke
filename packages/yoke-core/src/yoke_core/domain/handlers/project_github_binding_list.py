"""Hosted-service inventory of the authorized org's GitHub bindings."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest, FunctionError, HandlerOutcome,
)
from yoke_contracts.github_binding_metadata import GitHubIdentifier
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.function_org_context_resolution import resolve_org_context
from yoke_core.domain.project_github_binding_inventory import (
    list_project_github_bindings,
)
from yoke_core.domain.pydantic_validation_safety import safe_validation_message


class ProjectGithubBindingListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    org_id: int | None = Field(default=None, strict=True, gt=0)
    installation_id: GitHubIdentifier | None = None


class ProjectGithubBindingRow(BaseModel):
    project_id: int
    project: str
    installation_id: str
    repository_id: str
    github_repo: str
    api_url: str


class ProjectGithubBindingListResponse(BaseModel):
    rows: list[ProjectGithubBindingRow]


def handle_project_github_binding_list(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        parsed = ProjectGithubBindingListRequest(**(request.payload or {}))
    except ValidationError as exc:
        return HandlerOutcome(primary_success=False, error=FunctionError(
            code="payload_invalid", message=safe_validation_message(exc),
            jsonpath="$.payload",
        ))
    conn = connect()
    try:
        org_id = resolve_org_context(conn, request)
        if org_id is None:
            return HandlerOutcome(primary_success=False, error=FunctionError(
                code="not_found", message="The target organization was not found.",
                recovery_hint="Name an existing organization with org_id.",
                jsonpath="$.payload.org_id",
            ))
        rows = list_project_github_bindings(
            conn, org_id=org_id, installation_id=parsed.installation_id,
        )
        return HandlerOutcome(primary_success=True, result_payload={"rows": rows})
    finally:
        conn.close()
