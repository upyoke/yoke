"""Registered deployment-run membership and composition operations."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.deploy_lock import deploy_lock_refusal
from yoke_core.domain.handlers.deployment_common import error, run_id


class DeploymentRunAddItemRequest(BaseModel):
    run_id: str


class DeploymentRunAddItemResponse(BaseModel):
    run_id: str
    item_id: int
    message: str


class DeploymentRunValidateCompositionRequest(BaseModel):
    run_id: Optional[str] = None


class DeploymentRunValidateCompositionResponse(BaseModel):
    run_id: str
    valid: bool
    message: str


def _project_for_run(
    resolved_run_id: str,
    *,
    run_id_jsonpath: str,
) -> str | HandlerOutcome:
    from yoke_core.domain.deployment_runs_crud_query import cmd_get

    project = cmd_get(resolved_run_id, field="project")
    if project is None:
        return error(
            "not_found",
            f"deployment run '{resolved_run_id}' not found",
            jsonpath=run_id_jsonpath,
        )
    return str(project)


def _require_deploy_lock(
    request: FunctionCallRequest,
    resolved_run_id: str,
    *,
    run_id_jsonpath: str,
) -> HandlerOutcome | None:
    project = _project_for_run(
        resolved_run_id,
        run_id_jsonpath=run_id_jsonpath,
    )
    if isinstance(project, HandlerOutcome):
        return project
    refusal = deploy_lock_refusal(
        project,
        operation=request.function,
        session_id=request.actor.session_id,
    )
    if refusal is not None:
        return error("deploy_lock_required", refusal)
    return None


def handle_deployment_run_add_item(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    if request.target.kind != "item" or request.target.item_id is None:
        return error(
            "target_invalid",
            "deployment_runs.add_item requires a resolved item target",
            jsonpath="$.target.kind",
        )
    payload = request.payload or {}
    raw_run_id = payload.get("run_id")
    if not isinstance(raw_run_id, str) or not raw_run_id.strip():
        return error(
            "payload_invalid",
            "run_id must be a non-empty string",
            jsonpath="$.payload.run_id",
        )
    resolved_run_id = raw_run_id.strip()
    if refusal := _require_deploy_lock(
        request,
        resolved_run_id,
        run_id_jsonpath="$.payload.run_id",
    ):
        return refusal

    from yoke_core.domain.deployment_runs_crud_mutate import cmd_add_item

    try:
        message = cmd_add_item(resolved_run_id, int(request.target.item_id))
    except LookupError as exc:
        return error("not_found", str(exc))
    except ValueError as exc:
        return error("membership_rejected", str(exc))
    return HandlerOutcome(
        result_payload={
            "run_id": resolved_run_id,
            "item_id": int(request.target.item_id),
            "message": message,
        },
        primary_success=True,
    )


def handle_deployment_run_validate_composition(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    resolved_run_id = run_id(request, "deployment_runs.validate_composition")
    if isinstance(resolved_run_id, HandlerOutcome):
        return resolved_run_id
    if refusal := _require_deploy_lock(
        request,
        resolved_run_id,
        run_id_jsonpath="$.target.workflow_run_id",
    ):
        return refusal

    from yoke_core.domain.deployment_runs_validation import (
        cmd_validate_composition,
    )

    valid, message = cmd_validate_composition(resolved_run_id)
    if not valid:
        return error("composition_invalid", message)
    return HandlerOutcome(
        result_payload={
            "run_id": resolved_run_id,
            "valid": True,
            "message": message,
        },
        primary_success=True,
    )


__all__ = [
    "DeploymentRunAddItemRequest",
    "DeploymentRunAddItemResponse",
    "DeploymentRunValidateCompositionRequest",
    "DeploymentRunValidateCompositionResponse",
    "handle_deployment_run_add_item",
    "handle_deployment_run_validate_composition",
]
