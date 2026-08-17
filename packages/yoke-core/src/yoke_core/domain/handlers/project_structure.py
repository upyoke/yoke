"""Project Structure handlers.

Mutation path:
``project_structure.patch.apply`` wraps
:func:`yoke_core.domain.project_structure_write.apply_patch` without forking
the validation or transaction semantics. The op list is atomic: either every
op lands or the transaction is rolled back and the handler returns
``payload_invalid`` / ``policy_violation`` with the original error message.

Project Structure mutations are project-scoped configuration writes. The
dispatcher requires project-admin permission before this handler runs; an
optional item target is provenance context, not mutation authority.

Read path:
``project_structure.deploy_defaults.get`` exposes the project's default
deployment flow over the registered function surface.
``project_structure.get`` exposes ``read_structure`` over the same
relay so HTTPS clients can read family slices such as ``test_roots``.
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


class ProjectStructureDeployDefaultsGetRequest(BaseModel):
    project_id: str


class ProjectStructureDeployDefaultsGetResponse(BaseModel):
    project_id: str
    deployment_flow: Optional[str] = None


class ProjectStructureGetRequest(BaseModel):
    project_id: str
    family: Optional[str] = None


class ProjectStructureGetResponse(BaseModel):
    project_id: str
    family: Optional[str] = None
    entries: Optional[List[Dict[str, Any]]] = None
    families: Optional[Dict[str, List[Dict[str, Any]]]] = None


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


def handle_project_structure_get(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    from yoke_core.domain.project_structure import (
        UsageError,
        ValidationError,
        read_structure,
    )

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
    raw_family = payload.get("family")
    family = raw_family.strip() if isinstance(raw_family, str) else None
    try:
        result = read_structure(project_id, family=family)
    except (UsageError, ValidationError) as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=str(exc),
                jsonpath="$.payload.family",
            ),
        )
    return HandlerOutcome(result_payload=result, primary_success=True)


class ArchitectureHealthGetRequest(BaseModel):
    project_id: str | int | None = None


class ArchitectureHealthGetResponse(BaseModel):
    project_id: str
    health: dict


class ArchitectureDraftGetRequest(BaseModel):
    project_id: str | int | None = None


class ArchitectureDraftGetResponse(BaseModel):
    project_id: str
    payload: dict
    notes: list


def _architecture_project_id(request: FunctionCallRequest):
    payload = request.payload or {}
    return (
        request.target.project_id
        or _payload_project_id(payload)
        or payload.get("project")
    )


def _missing_project() -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(
            code="payload_invalid",
            message="project_id is required",
            jsonpath="$.payload.project_id",
        ),
    )


def handle_architecture_health_get(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """Coverage and violations for the project's declared map."""
    from yoke_core.domain import db_helpers
    from yoke_core.domain.architecture_health import (
        compute_architecture_health,
    )

    project_id = _architecture_project_id(request)
    if project_id is None:
        return _missing_project()
    with db_helpers.connect() as conn:
        health = compute_architecture_health(conn, project_id)
    return HandlerOutcome(
        result_payload={"project_id": str(project_id), "health": health},
        primary_success=True,
    )


def handle_architecture_draft_get(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """Scan-derived draft map proposal for operator review."""
    from yoke_core.domain import db_helpers
    from yoke_core.domain.architecture_map_survey import (
        draft_architecture_map,
    )

    project_id = _architecture_project_id(request)
    if project_id is None:
        return _missing_project()
    with db_helpers.connect() as conn:
        draft = draft_architecture_map(conn, project_id)
    return HandlerOutcome(
        result_payload={
            "project_id": str(project_id),
            "payload": draft["payload"],
            "notes": draft["notes"],
        },
        primary_success=True,
    )


__all__ = [
    "ArchitectureDraftGetRequest",
    "ArchitectureDraftGetResponse",
    "ArchitectureHealthGetRequest",
    "ArchitectureHealthGetResponse",
    "ProjectStructurePatchApplyRequest",
    "ProjectStructurePatchApplyResponse",
    "ProjectStructureDeployDefaultsGetRequest",
    "ProjectStructureDeployDefaultsGetResponse",
    "ProjectStructureGetRequest",
    "ProjectStructureGetResponse",
    "handle_architecture_draft_get",
    "handle_architecture_health_get",
    "handle_project_structure_patch_apply",
    "handle_project_structure_deploy_defaults_get",
    "handle_project_structure_get",
]
