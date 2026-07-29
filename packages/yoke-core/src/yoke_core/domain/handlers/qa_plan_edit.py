"""Registered full-document QA plan editing."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class PlanEditCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_key: str = Field(..., min_length=1)
    position: int = Field(..., ge=1)
    method_id: str = Field(..., min_length=1)
    instructions: str = Field(..., min_length=1)
    expected_outcome: str = Field(..., min_length=1)
    method_config: Dict[str, Any] = Field(default_factory=dict)
    success_policy_id: Optional[str] = None
    success_policy_params: Optional[Dict[str, Any]] = None
    host_baselines: List[str] = Field(default_factory=list)
    entry_surface: Optional[str] = None
    required_completion: Optional[str] = None


class PlanEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str = Field(..., min_length=1)
    slug: str = Field(..., min_length=1)
    base_updated_at: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = ""
    success_policy_id: str = "all-pass"
    success_policy_params: Dict[str, Any] = Field(default_factory=dict)
    target_environment_id: Optional[str] = Field(default=None, min_length=1)
    cases: List[PlanEditCase] = Field(..., min_length=1)


class PlanEditResponse(BaseModel):
    plan_id: int
    project_id: int
    project: str
    slug: str
    case_count: int
    updated_at: str
    unchanged: bool


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
    from yoke_core.domain.qa_plan_edit import (
        QaPlanConflictError,
        edit_plan,
    )
    from yoke_core.domain.qa_plan_management import QaPlanError

    try:
        with connect() as conn:
            result = edit_plan(
                conn,
                **payload.model_dump(mode="python"),
            )
    except QaPlanConflictError as exc:
        return _error("conflict", str(exc), "$.payload.base_updated_at")
    except QaPlanError as exc:
        return _error("incompatible", str(exc), "$.payload")
    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "PlanEditCase",
    "PlanEditRequest",
    "PlanEditResponse",
    "handle_plan_edit",
]
