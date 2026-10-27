"""Registered retirement of one project QA plan."""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class PlanRetireRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str = Field(..., min_length=1)
    #: Plan slug, or its numeric id.
    plan: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


class PlanRetireResponse(BaseModel):
    plan_id: int
    project: str
    slug: str
    retired_at: Any
    retirement_reason: Optional[str] = None
    retired_by_actor_id: Optional[int] = None
    #: True when the plan was already retired; the recorded retirement is
    #: returned unchanged.
    already_retired: bool
    #: Unexecuted requirement copies on finished items that retirement
    #: retracted in the same transaction.
    retracted_requirement_ids: List[int] = []


def _error(code: str, message: str, jsonpath: str = "$.payload") -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def handle_plan_retire(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "global":
        return _error(
            "target_invalid",
            "qa.plan.retire requires target.kind='global'",
            "$.target.kind",
        )
    try:
        payload = PlanRetireRequest.model_validate(request.payload or {})
    except ValueError as exc:
        return _error("payload_invalid", str(exc))

    from yoke_core.domain.actor_project_visibility import numeric_actor_id
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_plan_management import QaPlanError
    from yoke_core.domain.qa_plan_retire import (
        DEPENDENTS_CODE,
        retire_plan,
    )

    actor = request.actor
    try:
        with connect() as conn:
            result = retire_plan(
                conn,
                project=payload.project,
                plan=payload.plan,
                reason=payload.reason,
                actor_id=numeric_actor_id(actor.actor_id if actor else None),
            )
    except QaPlanError as exc:
        message = str(exc)
        code = message.split(":", 1)[0]
        if code not in {DEPENDENTS_CODE, "qa_plan_not_found"}:
            code = "incompatible"
        return _error(code, message)
    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "PlanRetireRequest",
    "PlanRetireResponse",
    "handle_plan_retire",
]
