"""Read handler for the client-local QA plan-case execution contract."""

from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class CaseExecutionGetRequest(BaseModel):
    pass


class CaseExecutionGetResponse(BaseModel):
    case: Dict[str, Any]


def _error(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def handle_case_execution_get(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    requirement_id = request.target.qa_requirement_id
    if request.target.kind != "qa_requirement" or requirement_id is None:
        return _error(
            "target_invalid",
            "qa.case_execution.get requires target.kind='qa_requirement'",
            "$.target",
        )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_case_execution_context import (
        QaCaseExecutionError,
        get_case_execution_context,
    )

    try:
        with connect() as conn:
            result = get_case_execution_context(
                conn, requirement_id=int(requirement_id),
            )
    except QaCaseExecutionError as exc:
        return _error("not_found", str(exc), "$.target.qa_requirement_id")
    return HandlerOutcome(
        result_payload={"case": result},
        primary_success=True,
    )


__all__ = [
    "CaseExecutionGetRequest",
    "CaseExecutionGetResponse",
    "handle_case_execution_get",
]
