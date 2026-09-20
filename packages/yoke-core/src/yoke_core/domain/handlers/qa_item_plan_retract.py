"""Retract a mis-specified item plan attachment."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ItemRetractRequest(BaseModel):
    project: str = Field(..., min_length=1)
    plan_id: int
    transition_id: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
    source: str = "agent"


class ItemRetractResponse(BaseModel):
    result: dict


def _error(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def handle_item_retract(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "item":
        return _error(
            "target_invalid",
            "qa.item_plan.retract requires target.kind='item'",
            "$.target.kind",
        )
    item_id = request.target.item_id
    if item_id is None:
        return _error("target_invalid", "item id is required", "$.target")
    try:
        payload = ItemRetractRequest.model_validate(request.payload or {})
    except ValueError as exc:
        return _error("payload_invalid", str(exc), "$.payload")
    if payload.source not in {"agent", "operator"}:
        return _error(
            "payload_invalid",
            "source must be one of ['agent', 'operator']",
            "$.payload.source",
        )
    from yoke_core.domain.actor_project_visibility import numeric_actor_id
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.handlers.qa_plan_writes import _project_matches
    from yoke_core.domain.qa_plan_attachment_retract import retract_plan_from_item
    from yoke_core.domain.qa_plan_management import QaPlanError

    actor_id: Optional[int] = numeric_actor_id(
        request.actor.actor_id if request.actor else None
    )
    try:
        with connect() as conn:
            _project_matches(
                conn,
                plan_id=payload.plan_id,
                project=payload.project,
            )
            result = retract_plan_from_item(
                conn,
                item_id=int(item_id),
                plan_id=payload.plan_id,
                transition_id=payload.transition_id,
                reason=payload.reason,
                actor_id=actor_id,
                source=payload.source,
            )
    except QaPlanError as exc:
        return _error("incompatible", str(exc), "$.payload")
    return HandlerOutcome(result_payload={"result": result}, primary_success=True)


__all__ = [
    "ItemRetractRequest",
    "ItemRetractResponse",
    "handle_item_retract",
]
