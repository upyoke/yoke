"""Reads and doorman actions for one materialized QA plan case."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class CaseExecutionBeginRequest(BaseModel):
    pass


class CaseExecutionBeginResponse(BaseModel):
    case: Dict[str, Any]


class CaseWaiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rationale: str = Field(min_length=1)


class CaseWaiveResponse(BaseModel):
    requirement_id: int
    source: str
    waived: bool


def _error(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _requirement_id(
    request: FunctionCallRequest,
    *,
    function_id: str,
) -> tuple[Optional[int], Optional[HandlerOutcome]]:
    requirement_id = request.target.qa_requirement_id
    if request.target.kind != "qa_requirement" or requirement_id is None:
        return None, _error(
            "target_invalid",
            f"{function_id} requires target.kind='qa_requirement'",
            "$.target",
        )
    return int(requirement_id), None


def _handler_for(function_id: str):
    from yoke_core.domain.handlers import qa_requirement_waive

    return {
        "qa.requirement.waive": (
            qa_requirement_waive.handle_qa_requirement_waive
        ),
    }.get(function_id)


def handle_case_execution_begin(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    requirement_id = request.target.qa_requirement_id
    if request.target.kind != "qa_requirement" or requirement_id is None:
        return _error(
            "target_invalid",
            f"{request.function} requires target.kind='qa_requirement'",
            "$.target",
        )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_case_execution_context import (
        QaCaseExecutionError,
        execution_host_capability_kinds,
        get_case_execution_context,
    )
    from yoke_core.domain.qa_start_bound_authority import (
        PAYLOAD_KEY,
        resolve_start_bound_claim_id,
    )

    try:
        with connect() as conn:
            host_capabilities = execution_host_capability_kinds(
                conn,
                session_id=request.actor.session_id,
            )
            result = get_case_execution_context(
                conn,
                requirement_id=int(requirement_id),
                host_capability_kinds=host_capabilities,
            )
            # The dispatcher just verified this session's claim to admit
            # the call. Hand that verified claim back on the contract so
            # the run records against it later instead of re-deriving
            # authority from a claim table an hour of suite has moved on.
            item_id = result.get("item_id")
            if item_id is not None:
                result[PAYLOAD_KEY] = resolve_start_bound_claim_id(
                    conn,
                    item_id=int(item_id),
                    session_id=request.actor.session_id,
                )
    except QaCaseExecutionError as exc:
        return _error("not_found", str(exc), "$.target.qa_requirement_id")
    return HandlerOutcome(
        result_payload={"case": result},
        primary_success=True,
    )


def handle_case_waive(request: FunctionCallRequest) -> HandlerOutcome:
    requirement_id, invalid = _requirement_id(
        request,
        function_id="qa.case.waive",
    )
    if invalid is not None:
        return invalid
    try:
        body = CaseWaiveRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error("payload_invalid", str(exc), "$.payload")

    nested = request.model_copy(
        update={
            "function": "qa.requirement.waive",
            "payload": {
                "rationale": body.rationale,
                "source": "operator",
                "force": True,
            },
        }
    )
    outcome = _handler_for("qa.requirement.waive")(nested)
    return outcome


__all__ = [
    "CaseExecutionBeginRequest",
    "CaseExecutionBeginResponse",
    "CaseWaiveRequest",
    "CaseWaiveResponse",
    "handle_case_execution_begin",
    "handle_case_waive",
]
