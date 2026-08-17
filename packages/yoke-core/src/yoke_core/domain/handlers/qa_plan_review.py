"""Registered authority for batched agent review of a QA plan execution."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.handlers.qa_plan_execution import (
    PlanExecutionStateRequest,
    _owned_execution,
)


class PlanReviewBeginRequest(PlanExecutionStateRequest):
    pass


class AgentVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: int = Field(ge=1)
    verdict: str = Field(pattern="^(pass|fail|inconclusive)$")
    rationale: str = Field(min_length=1, max_length=8000)


class PlanReviewSubmitRequest(PlanExecutionStateRequest):
    model_config = ConfigDict(extra="forbid")

    bundle_id: str = Field(min_length=1)
    bundle_digest: str = Field(min_length=64, max_length=64)
    verdicts: list[AgentVerdict] = Field(min_length=1)


class PlanReviewBeginResponse(BaseModel):
    execution_id: str
    state: str
    review_bundle: dict[str, Any] | None


class PlanReviewSubmitResponse(BaseModel):
    execution_id: str
    bundle_id: str
    state: str
    submission: str
    verdicts: list[dict[str, Any]]


def _error(code: str, message: str, jsonpath: str = "$.payload") -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _parse(model: type[BaseModel], payload: Any) -> BaseModel | HandlerOutcome:
    try:
        return model.model_validate(payload or {})
    except ValidationError as exc:
        return _error("payload_invalid", str(exc))


def handle_plan_review_begin(request: FunctionCallRequest) -> HandlerOutcome:
    parsed = _parse(PlanReviewBeginRequest, request.payload)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    assert isinstance(parsed, PlanReviewBeginRequest)
    owned = _owned_execution(request, parsed)
    if isinstance(owned, HandlerOutcome):
        return owned
    conn, execution = owned
    try:
        from yoke_core.domain.qa_plan_review import (
            QaPlanReviewError,
            begin_plan_review,
        )

        review_bundle = begin_plan_review(conn, execution)
        result = {
            "execution_id": str(execution["id"]),
            "state": (
                str(execution["state"]) if review_bundle is not None else "not_required"
            ),
            "review_bundle": review_bundle,
        }
    except (QaPlanReviewError, ValueError) as exc:
        conn.rollback()
        return _error("plan_review_begin_failed", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)


def handle_plan_review_submit(request: FunctionCallRequest) -> HandlerOutcome:
    parsed = _parse(PlanReviewSubmitRequest, request.payload)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    assert isinstance(parsed, PlanReviewSubmitRequest)
    owned = _owned_execution(request, parsed)
    if isinstance(owned, HandlerOutcome):
        return owned
    conn, execution = owned
    try:
        if execution["state"] not in {"awaiting_agent_review", "completed"}:
            raise ValueError("QA plan execution is not awaiting agent review")
        from yoke_core.domain.qa_plan_review import QaPlanReviewError
        from yoke_core.domain.qa_plan_review_submission import (
            submit_plan_review,
        )

        result = submit_plan_review(
            conn,
            execution,
            bundle_id=parsed.bundle_id,
            bundle_digest=parsed.bundle_digest,
            verdicts=[row.model_dump() for row in parsed.verdicts],
            reviewer_actor_id=request.actor.actor_id,
            reviewer_session_id=request.actor.session_id,
        )
    except (QaPlanReviewError, ValueError) as exc:
        conn.rollback()
        return _error("plan_review_submit_failed", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)


__all__ = [
    "AgentVerdict",
    "PlanReviewBeginRequest",
    "PlanReviewBeginResponse",
    "PlanReviewSubmitRequest",
    "PlanReviewSubmitResponse",
    "handle_plan_review_begin",
    "handle_plan_review_submit",
]
