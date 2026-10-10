"""Operator publication of full immutable workflow definitions."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class WorkflowVersionPublishRequest(BaseModel):
    workflow_id: str = Field(min_length=1)
    definition: dict[str, Any]
    reason: str = Field(min_length=1)
    expected_current_version: int | None = Field(default=None, ge=1)
    keep_current: bool = False


class WorkflowVersionPublishResponse(BaseModel):
    workflow_id: str
    version: int
    version_id: int
    definition_digest: str
    current: bool


def handle_workflows_version_publish(request: FunctionCallRequest) -> HandlerOutcome:
    def refuse(code, message, path):
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(code=code, message=message, jsonpath=path),
        )

    if request.target.kind != "global":
        return refuse(
            "target_invalid",
            "workflows.version.publish requires target.kind='global'; use a global target",
            "$.target.kind",
        )
    try:
        payload = WorkflowVersionPublishRequest.model_validate(request.payload or {})
    except ValueError as exc:
        return refuse(
            "payload_invalid",
            f"{exc}; supply a definition object and a non-empty reason",
            "$.payload",
        )
    from yoke_core.domain.actor_project_visibility import numeric_actor_id
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.workflow_definition_codec import WorkflowRegistryError
    from yoke_core.domain.workflow_definition_validation import WorkflowDefinitionError
    from yoke_core.domain.workflow_publication import publish_workflow_version

    try:
        with connect() as conn:
            result = publish_workflow_version(
                conn,
                **payload.model_dump(),
                require_expected_current=True,
                published_by_actor_id=numeric_actor_id(
                    request.actor.actor_id if request.actor else None
                ),
            )
    except WorkflowDefinitionError as exc:
        return refuse(
            "workflow_definition_invalid",
            f"{exc}; correct the definition and publish again",
            "$.payload.definition",
        )
    except WorkflowRegistryError as exc:
        return refuse(str(exc).split(":", 1)[0], str(exc), "$.payload")
    return HandlerOutcome(primary_success=True, result_payload=result)
