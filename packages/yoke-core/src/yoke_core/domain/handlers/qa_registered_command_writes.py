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


class RegisteredCommandSetResponse(BaseModel):
    project: str
    scope: str
    plan_id: int
    qa_phase: str
    workflow_ids: List[str]
    transitions: Dict[str, str]
    ci_workflow: str
    method_id: str


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
    case replacement, and default attachment — and without naming a deploy
    environment the ``command`` and ``command-ci`` methods never read.
    """
    payload, error = _payload(request)
    if error is not None:
        return error
    assert payload is not None

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.project_identity import resolve_project
    from yoke_core.domain.qa_command_plan_registration import (
        CI_COMMAND_METHOD_ID,
        LOCAL_COMMAND_METHOD_ID,
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
            )
    except ValueError as exc:
        return _error("incompatible", str(exc), "$.payload")

    ci_workflow = str(result.get("ci_workflow") or "")
    result["method_id"] = (
        CI_COMMAND_METHOD_ID if ci_workflow else LOCAL_COMMAND_METHOD_ID
    )
    result["ci_workflow"] = ci_workflow
    return HandlerOutcome(result_payload={"result": result}, primary_success=True)


__all__ = [
    "RegisteredCommandSetRequest",
    "RegisteredCommandSetResponse",
    "handle_registered_command_set",
]
