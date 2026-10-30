"""Handlers for project GitHub App repository bindings."""

from __future__ import annotations

from typing import Annotated, Any, Dict, Literal, Optional

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    SecretStr,
    StrictBool,
    ValidationError,
)

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.github_binding_metadata import GitHubIdentifier
from yoke_core.domain.actor_project_visibility import (
    actor_visible_project_ids,
    numeric_actor_id,
)
from yoke_core.domain.pydantic_validation_safety import safe_validation_message


def _project_reference(value: Any) -> str:
    """Accept a project slug or id; JSON numbers arrive as integers."""

    if isinstance(value, bool):
        raise ValueError("must be a project slug or numeric project id")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value
    raise ValueError("must be a project slug or numeric project id")


ProjectReference = Annotated[str, BeforeValidator(_project_reference)]


class ProjectGithubBindingBindRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: ProjectReference
    installation_id: GitHubIdentifier
    repository_id: GitHubIdentifier
    github_repo: str
    expected_api_url: str
    github_user_access_token: SecretStr


class ProjectGithubBindingUnbindRequest(BaseModel):
    project: ProjectReference


class ProjectGithubBindingStatusRequest(BaseModel):
    project: ProjectReference


class ProjectGithubBindingCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: ProjectReference


class ProjectGithubBindingLifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: ProjectReference
    installation_id: GitHubIdentifier
    repository_id: GitHubIdentifier
    installation_status: Literal["active", "pending", "suspended", "deleted"]
    repository_available: StrictBool
    permissions: Optional[Dict[str, str]] = None


class ProjectGithubBindingStatusResponse(BaseModel):
    skipped: Optional[str] = None
    project: str
    github_repo: str
    default_branch: str
    github_sync_mode: str
    bound: bool
    binding: Optional[Dict[str, Any]] = None
    installation: Optional[Dict[str, Any]] = None
    previous_sync_mode: Optional[str] = None
    sync_mode: Optional[str] = None
    sync_mode_notice: Optional[str] = None
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

    resolved_project = parsed.project
    actor_id = numeric_actor_id(request.actor.actor_id if request.actor else None)
    if actor_id is not None:
        from yoke_core.domain.db_helpers import connect
        from yoke_core.domain.project_identity import resolve_project

        conn = connect()
        try:
            identity = resolve_project(
                conn,
                parsed.project,
                required=False,
                visible_project_ids=actor_visible_project_ids(conn, actor_id),
            )
        finally:
            conn.close()
        if identity is None:
            return HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="not_found",
                    message=f"project '{parsed.project}' not found",
                    jsonpath="$.payload.project",
                ),
            )
        resolved_project = str(identity.id)

    try:
        result = cmd_project_github_binding_status(resolved_project)
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


def handle_project_github_binding_check(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        parsed = ProjectGithubBindingCheckRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _payload_invalid(exc)

    from yoke_core.domain.github_app_server_installation import (
        GitHubServerInstallationVerificationError,
    )
    from yoke_core.domain.github_app_token_models import GitHubAppTokenError
    from yoke_core.domain.github_app_user_verification_transport import (
        GitHubUserVerificationError,
    )
    from yoke_core.domain.project_github_auth_models import ProjectGithubAuthError
    from yoke_core.domain.project_github_binding_check import (
        CHECK_RECIPE,
        ProjectGithubBindingCheckError,
        cmd_check_project_github_binding,
    )
    from yoke_core.domain.project_github_binding_persistence import (
        ProjectGithubBindingError,
    )

    try:
        result = cmd_check_project_github_binding(parsed.project)
    except ProjectGithubBindingCheckError as exc:
        return _check_refused(exc.code, str(exc), exc.recovery)
    except ProjectGithubAuthError as exc:
        return _check_refused(
            exc.code,
            str(exc),
            exc.repair_hint
            or CHECK_RECIPE.format(
                project=parsed.project,
            ),
        )
    except (
        GitHubUserVerificationError,
        GitHubServerInstallationVerificationError,
        GitHubAppTokenError,
        ProjectGithubBindingError,
    ) as exc:
        return _check_refused(
            "github_check_refused_by_github",
            f"GitHub did not confirm the binding: {exc}",
            "Open the installation's repository access on GitHub, confirm "
            "the App still reaches the repository, then check again",
        )
    except LookupError as exc:
        return _check_refused("not_found", str(exc), "Name an existing project")
    return HandlerOutcome(result_payload=result, primary_success=True)


def _check_refused(code: str, message: str, recovery: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(
            code=code,
            message=message,
            jsonpath="$.payload.project",
            recovery_hint=f"{recovery}.",
        ),
    )


def handle_project_github_binding_lifecycle(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        parsed = ProjectGithubBindingLifecycleRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _payload_invalid(exc)

    from yoke_core.domain.project_github_binding_lifecycle import (
        ProjectGithubBindingLifecycleError,
        cmd_apply_project_github_binding_lifecycle,
    )

    try:
        result = cmd_apply_project_github_binding_lifecycle(
            parsed.project,
            installation_id=parsed.installation_id,
            repository_id=parsed.repository_id,
            installation_status=parsed.installation_status,
            repository_available=parsed.repository_available,
            permissions=parsed.permissions,
        )
    except (LookupError, ProjectGithubBindingLifecycleError, ValueError) as exc:
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
    "ProjectReference",
    "ProjectGithubBindingBindRequest",
    "ProjectGithubBindingCheckRequest",
    "ProjectGithubBindingLifecycleRequest",
    "ProjectGithubBindingStatusRequest",
    "ProjectGithubBindingStatusResponse",
    "ProjectGithubBindingUnbindRequest",
    "handle_project_github_binding_bind",
    "handle_project_github_binding_check",
    "handle_project_github_binding_lifecycle",
    "handle_project_github_binding_status",
    "handle_project_github_binding_unbind",
]
