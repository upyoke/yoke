"""Project Structure handlers.

Mutation path:
``project_structure.patch.apply`` wraps
:func:`yoke_core.domain.project_structure_write.apply_patch` without forking
the validation or transaction semantics. The op list is atomic: either every
op lands or the transaction is rolled back and the handler returns
``payload_invalid`` / ``policy_violation`` with the original error message.

``claim_required_kind="item"`` — Project Structure mutations are item-scoped
because they typically land alongside a ticket's spec change. The active
claim's session is verified by the dispatcher before this handler runs.

Read path:
``project_structure.command_definitions.{get,list}`` exposes the
agent-facing Project Test Command readers over the registered function
surface, routing through the existing command_definitions domain helper.
``project_structure.deploy_defaults.get`` exposes the project's default
deployment flow over the same registered surface.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ProjectStructurePatchApplyRequest(BaseModel):
    project_id: str
    ops: List[Dict[str, Any]]
    actor: Optional[str] = None


class ProjectStructurePatchApplyResponse(BaseModel):
    project_id: str
    applied_ops: List[Dict[str, Any]]


class ProjectStructureCommandDefinitionsGetRequest(BaseModel):
    project_id: str
    scope: str


class ProjectStructureCommandDefinitionsGetResponse(BaseModel):
    project_id: str
    scope: str
    command: Optional[str] = None


class ProjectStructureCommandDefinitionsListRequest(BaseModel):
    project_id: str


class ProjectStructureCommandDefinitionsListResponse(BaseModel):
    project_id: str
    commands: Dict[str, str]


class ProjectStructureDeployDefaultsGetRequest(BaseModel):
    project_id: str


class ProjectStructureDeployDefaultsGetResponse(BaseModel):
    project_id: str
    deployment_flow: Optional[str] = None


def _payload_project_id(payload: Dict[str, Any]) -> Optional[str]:
    value = payload.get("project_id")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def handle_project_structure_patch_apply(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    from yoke_core.domain.project_structure import UsageError, ValidationError
    from yoke_core.domain.project_structure_write import apply_patch

    payload = request.payload or {}
    project_id = payload.get("project_id")
    ops = payload.get("ops")
    actor = payload.get("actor") or request.actor.actor_id
    if not isinstance(project_id, str) or not project_id:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="project_id is required",
                jsonpath="$.payload.project_id",
            ),
        )
    if not isinstance(ops, list) or len(ops) == 0:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="ops must be a non-empty list",
                jsonpath="$.payload.ops",
            ),
        )

    try:
        result = apply_patch(project_id, ops, actor=actor)
    except UsageError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=str(exc),
                jsonpath="$.payload.ops",
            ),
        )
    except ValidationError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="policy_violation",
                message=str(exc),
                jsonpath="$.payload.ops",
            ),
        )
    return HandlerOutcome(
        result_payload={
            "project_id": str(result.get("project_id") or project_id),
            "applied_ops": list(result.get("applied_ops") or []),
        },
        primary_success=True,
    )


def handle_project_structure_command_definitions_get(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    from yoke_core.domain import command_definitions

    payload = request.payload or {}
    project_id = _payload_project_id(payload)
    scope = payload.get("scope")
    if project_id is None:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="project_id is required",
                jsonpath="$.payload.project_id",
            ),
        )
    if not isinstance(scope, str) or not scope.strip():
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="scope is required",
                jsonpath="$.payload.scope",
            ),
        )

    scope = scope.strip()
    try:
        command = command_definitions.get_command(project_id, scope)
    except ValueError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=str(exc),
                jsonpath="$.payload.scope",
            ),
        )
    return HandlerOutcome(
        result_payload={
            "project_id": project_id,
            "scope": scope,
            "command": command,
        },
        primary_success=True,
    )


def handle_project_structure_command_definitions_list(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    from yoke_core.domain import command_definitions

    payload = request.payload or {}
    project_id = _payload_project_id(payload)
    if project_id is None:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="project_id is required",
                jsonpath="$.payload.project_id",
            ),
        )
    commands = command_definitions.list_commands(project_id)
    return HandlerOutcome(
        result_payload={"project_id": project_id, "commands": commands},
        primary_success=True,
    )


def handle_project_structure_deploy_defaults_get(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    from yoke_core.domain import deploy_defaults

    payload = request.payload or {}
    project_id = _payload_project_id(payload)
    if project_id is None:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="project_id is required",
                jsonpath="$.payload.project_id",
            ),
        )
    flow = deploy_defaults.get_default_flow(project_id)
    return HandlerOutcome(
        result_payload={
            "project_id": project_id,
            "deployment_flow": flow,
        },
        primary_success=True,
    )


__all__ = [
    "ProjectStructurePatchApplyRequest",
    "ProjectStructurePatchApplyResponse",
    "ProjectStructureCommandDefinitionsGetRequest",
    "ProjectStructureCommandDefinitionsGetResponse",
    "ProjectStructureCommandDefinitionsListRequest",
    "ProjectStructureCommandDefinitionsListResponse",
    "ProjectStructureDeployDefaultsGetRequest",
    "ProjectStructureDeployDefaultsGetResponse",
    "handle_project_structure_patch_apply",
    "handle_project_structure_command_definitions_get",
    "handle_project_structure_command_definitions_list",
    "handle_project_structure_deploy_defaults_get",
]
