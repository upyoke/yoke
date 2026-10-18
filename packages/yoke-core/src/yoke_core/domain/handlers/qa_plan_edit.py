"""Registered full-document QA plan editing."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.qa_plan_case_document import QaPlanCaseDocument


class PlanEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str = Field(..., min_length=1)
    slug: str = Field(..., min_length=1)
    base_updated_at: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = ""
    success_policy_id: str = "all-pass"
    success_policy_params: Dict[str, Any] = Field(default_factory=dict)
    target_environment: Optional[str] = Field(default=None, min_length=1)
    cases: List[QaPlanCaseDocument] = Field(..., min_length=1)


class PlanEditResponse(BaseModel):
    plan_id: int
    project_id: int
    project: str
    slug: str
    case_count: int
    updated_at: str
    unchanged: bool
    #: Rows already materialized from this plan that the edit did not reach,
    #: each with the refresh command that does. An empty list is the whole
    #: answer: nothing is behind this plan.
    requirements_behind_plan: List[Dict[str, Any]] = []
    requirements_behind_plan_count: int = 0
    historical_requirements_excluded_count: int = 0


def _error(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def handle_plan_edit(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "global":
        return _error(
            "target_invalid",
            "qa.plan.edit requires target.kind='global'",
            "$.target.kind",
        )
    try:
        payload = PlanEditRequest.model_validate(request.payload or {})
    except ValueError as exc:
        return _error("payload_invalid", str(exc), "$.payload")

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_plan_case_currency import plan_drift_report
    from yoke_core.domain.qa_plan_edit import (
        QaPlanConflictError,
        edit_plan,
    )
    from yoke_core.domain.qa_plan_management import QaPlanError

    try:
        with connect() as conn:
            # A case field the document left out reaches the domain absent,
            # not defaulted, so the edit can refuse to reset a stored value.
            result = edit_plan(
                conn,
                **payload.model_dump(mode="python", exclude={"cases"}),
                cases=[
                    case.model_dump(mode="python", exclude_unset=True)
                    for case in payload.cases
                ],
            )
            # Read after the write commits, so the report names what is
            # behind the plan as it now stands rather than as it was read.
            result.update(plan_drift_report(conn, int(result["plan_id"])))
    except QaPlanConflictError as exc:
        return _error("conflict", str(exc), "$.payload.base_updated_at")
    except QaPlanError as exc:
        return _error("incompatible", str(exc), "$.payload")
    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "PlanEditRequest",
    "PlanEditResponse",
    "handle_plan_edit",
]
