"""``workflows.definition.get`` read handler.

Read-only: serves the engine's workflow definition (family, per-type
progressions, gate points) plus the deployment flows, optionally scoped
to one project. The payload shape and derivations live in
:mod:`yoke_core.domain.workflows_definition_read`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class WorkflowsDefinitionGetRequest(BaseModel):
    project: Optional[str] = None


class WorkflowsDefinitionGetResponse(BaseModel):
    family: str
    types: List[Dict[str, Any]]
    flows: List[Dict[str, Any]]


def _error(
    code: str,
    message: str,
    *,
    jsonpath: Optional[str] = None,
) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def handle_workflows_definition_get(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    if request.target.kind != "global":
        return _error(
            "target_invalid",
            "workflows.definition.get requires target.kind='global'",
            jsonpath="$.target.kind",
        )
    payload = request.payload or {}
    project = payload.get("project")
    if project is not None and not isinstance(project, str):
        return _error(
            "payload_invalid",
            "project must be a string when present",
            jsonpath="$.payload.project",
        )

    from yoke_core.domain.workflows_definition_read import (
        get_workflows_definition,
    )

    try:
        definition = get_workflows_definition(project=project)
    except LookupError as exc:
        return _error(
            "not_found", str(exc), jsonpath="$.payload.project",
        )
    return HandlerOutcome(
        result_payload=definition,
        primary_success=True,
    )


__all__ = [
    "WorkflowsDefinitionGetRequest",
    "WorkflowsDefinitionGetResponse",
    "handle_workflows_definition_get",
]
