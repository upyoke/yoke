"""Registered materialization handler for item and deployment-run QA plans."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class MaterializeRequest(BaseModel):
    transition_id: Optional[str] = Field(default=None, min_length=1)
    plan: Optional[str] = Field(default=None, min_length=1)
    project: Optional[str] = Field(default=None, min_length=1)


def _error(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def handle_materialize(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        payload = MaterializeRequest.model_validate(request.payload or {})
    except ValueError as exc:
        return _error("payload_invalid", str(exc), "$.payload")
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_plan_attachments import (
        materialize_for_deployment_run,
        materialize_for_item,
    )
    from yoke_core.domain.qa_plan_management import QaPlanError

    try:
        with connect() as conn:
            if request.target.kind == "item":
                item_id = request.target.item_id
                if item_id is None:
                    return _error(
                        "target_invalid",
                        "item id is required",
                        "$.target",
                    )
                if payload.transition_id is None:
                    return _error(
                        "payload_invalid",
                        "item materialization requires transition_id",
                        "$.payload.transition_id",
                    )
                if payload.plan is not None:
                    return _error(
                        "payload_invalid",
                        "item materialization uses attached plans, not plan",
                        "$.payload.plan",
                    )
                result = materialize_for_item(
                    conn,
                    item_id=int(item_id),
                    transition_id=payload.transition_id,
                )
            elif request.target.kind == "deployment_run":
                run_id = request.target.deployment_run_id
                if not run_id:
                    return _error(
                        "target_invalid",
                        "deployment run id is required",
                        "$.target",
                    )
                if payload.plan is None:
                    return _error(
                        "payload_invalid",
                        "deployment-run materialization requires plan",
                        "$.payload.plan",
                    )
                if payload.transition_id is not None:
                    return _error(
                        "payload_invalid",
                        "deployment-run materialization has no workflow transition",
                        "$.payload.transition_id",
                    )
                result = materialize_for_deployment_run(
                    conn,
                    deployment_run_id=str(run_id),
                    plan=payload.plan,
                    project=payload.project,
                )
            else:
                return _error(
                    "target_invalid",
                    "qa.plan.materialize requires an item or deployment run",
                    "$.target.kind",
                )
    except QaPlanError as exc:
        return _error("incompatible", str(exc), "$.payload")
    return HandlerOutcome(result_payload={"result": result}, primary_success=True)


__all__ = ["MaterializeRequest", "handle_materialize"]
