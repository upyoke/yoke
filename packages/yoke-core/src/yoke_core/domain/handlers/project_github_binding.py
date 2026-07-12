"""Handlers for project GitHub App repository bindings."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.pydantic_validation_safety import safe_validation_message


class ProjectGithubBindingBindRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str
    installation_id: str
    repository_id: str
    github_repo: str
    expected_api_url: str
    github_user_access_token: SecretStr


class ProjectGithubBindingUnbindRequest(BaseModel):
    project: str


class ProjectGithubBindingStatusRequest(BaseModel):
    project: str


class ProjectGithubBindingStatusResponse(BaseModel):
    project: str
    github_repo: str
    default_branch: str
    github_sync_mode: str
    bound: bool
    binding: Optional[Dict[str, Any]] = None
    installation: Optional[Dict[str, Any]] = None
    permission_status: Dict[str, Any]
    automation: Dict[str, Any]


def handle_project_github_binding_bind(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        parsed = ProjectGithubBindingBindRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _payload_invalid(exc)

    from yoke_core.domain.project_github_binding import (
        ProjectGithubBindingError,
        cmd_bind_project_repo,
    )

    try:
        result = cmd_bind_project_repo(
            project=parsed.project,
            installation_id=parsed.installation_id,
            repository_id=parsed.repository_id,
            github_repo=parsed.github_repo,
            expected_api_url=parsed.expected_api_url,
            github_user_access_token=(
                parsed.github_user_access_token.get_secret_value()
            ),
        )
    except (LookupError, ProjectGithubBindingError, ValueError) as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=str(exc),
                jsonpath="$.payload",
            ),
        )
    return HandlerOutcome(result_payload=result, primary_success=True)


def handle_project_github_binding_unbind(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        parsed = ProjectGithubBindingUnbindRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _payload_invalid(exc)

    from yoke_core.domain.project_github_binding import cmd_unbind_project_repo

    try:
        result = cmd_unbind_project_repo(parsed.project)
    except (LookupError, ValueError) as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=str(exc),
                jsonpath="$.payload",
            ),
        )
    return HandlerOutcome(result_payload=result, primary_success=True)


def handle_project_github_binding_status(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        parsed = ProjectGithubBindingStatusRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _payload_invalid(exc)

    from yoke_core.domain.project_github_binding import (
        cmd_project_github_binding_status,
    )

    try:
        result = cmd_project_github_binding_status(parsed.project)
    except (LookupError, ValueError) as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=str(exc),
                jsonpath="$.payload",
            ),
        )
    return HandlerOutcome(result_payload=result, primary_success=True)


def _payload_invalid(exc: ValidationError) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(
            code="payload_invalid",
            message=safe_validation_message(exc),
            jsonpath="$.payload",
        ),
    )


__all__ = [
    "ProjectGithubBindingBindRequest",
    "ProjectGithubBindingStatusRequest",
    "ProjectGithubBindingStatusResponse",
    "ProjectGithubBindingUnbindRequest",
    "handle_project_github_binding_bind",
    "handle_project_github_binding_status",
    "handle_project_github_binding_unbind",
]
