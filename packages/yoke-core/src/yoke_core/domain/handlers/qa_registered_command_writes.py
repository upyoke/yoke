"""Registered handler binding a project's verification command to its QA gate."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class RegisteredCommandSetRequest(BaseModel):
    project: str = Field(..., min_length=1)
    scope: str = Field(..., min_length=1)
    command: str = Field(..., min_length=1)
    target_environment: Optional[str] = None
    requires_base_url: Optional[bool] = None


class RegisteredCommandSetResponse(BaseModel):
    project: str
    scope: str
    plan_id: int
    qa_phase: str
    workflow_ids: List[str]
    transitions: Dict[str, str]
    ci_workflow: str
    method_id: str
    # What the declared workflow was checked against, and what could not be
    # checked here. A caller that binds CI needs to see an unverifiable
    # outcome named rather than read the binding as proof.
    ci_workflow_verification: str = ""
    ci_workflow_verification_detail: str = ""
    target_mode: str
    target_environment: Optional[str]
    requires_base_url: bool


def _error(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _payload(
    request: FunctionCallRequest,
) -> tuple[Optional[RegisteredCommandSetRequest], Optional[HandlerOutcome]]:
    if request.target.kind != "global":
        return None, _error(
            "target_invalid",
            f"{request.function} requires target.kind='global'",
            "$.target.kind",
        )
    try:
        return RegisteredCommandSetRequest(**(request.payload or {})), None
    except Exception as exc:  # noqa: BLE001 - surfaced as a typed function error
        return None, _error("payload_invalid", str(exc), "$.payload")


def handle_registered_command_set(request: FunctionCallRequest) -> HandlerOutcome:
    """Converge one scope's registered command onto its plan and gate defaults.

    The convergence itself already exists and is shared with the seed path:
    :func:`yoke_core.domain.qa_command_plan_registration.ensure_registered_command_plan`
    creates or revives the ``registered-command-{scope}`` plan, writes the case
    row, routes the case to the CI or local runner from the project's declared
    workflow, and converges the project-default rows at the transitions that
    gate. This handler is the public surface over that function so a project
    can bind its verification command without hand-composing plan creation,
    case replacement, and default attachment. Quick/full commands use a
    project target; deployed scopes select an environment or the local runtime
    base-URL contract before any binding is written.
    """
    payload, error = _payload(request)
    if error is not None:
        return error

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.project_identity import resolve_project
    from yoke_core.domain.qa_command_plan_registration import (
        ensure_registered_command_plan,
    )

    try:
        with connect() as conn:
            identity = resolve_project(conn, payload.project, required=False)
            if identity is None:
                return _error(
                    "not_found",
                    f"project {payload.project!r} not found",
                    "$.payload.project",
                )
            result: dict[str, Any] = ensure_registered_command_plan(
                conn,
                project_id=int(identity.id),
                project=identity.slug,
                scope=payload.scope,
                command=payload.command,
                target_environment=payload.target_environment,
                requires_base_url=payload.requires_base_url,
            )
    except ValueError as exc:
        return _error("incompatible", str(exc), "$.payload")

    return HandlerOutcome(result_payload={"result": result}, primary_success=True)


__all__ = [
    "RegisteredCommandSetRequest",
    "RegisteredCommandSetResponse",
    "handle_registered_command_set",
]
