"""Reads and doorman actions for one materialized QA plan case."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
    HandlerOutcome,
    TargetRef,
)


class CaseExecutionBeginRequest(BaseModel):
    pass


class CaseExecutionBeginResponse(BaseModel):
    case: Dict[str, Any]


class CaseRerunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = ""
    expected_branch: Optional[str] = None
    expected_sha: Optional[str] = None
    timeout_seconds: Optional[int] = Field(default=None, ge=1, le=7200)

    @model_validator(mode="after")
    def _freshness_pair(self) -> "CaseRerunRequest":
        if bool(self.expected_branch) != bool(self.expected_sha):
            raise ValueError(
                "expected_branch and expected_sha must be provided together"
            )
        return self


class CaseRerunResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    requirement_id: int
    executor_id: str
    verdict: Optional[str] = None
    case_outcome: Optional[str] = None


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
    from yoke_core.domain.handlers import (
        qa_artifact_presign,
        qa_browser,
        qa_browser_writes,
        qa_requirement_waive,
        test_machine_case,
    )

    return {
        "qa.case_execution.begin": handle_case_execution_begin,
        "qa.browser_context.get": qa_browser.handle_qa_browser_context_get,
        "qa.run.add": qa_browser_writes.handle_qa_run_add,
        "qa.run.complete": qa_browser_writes.handle_qa_run_complete,
        "qa.artifact.add": qa_browser_writes.handle_qa_artifact_add,
        "qa.artifact.presign": (qa_artifact_presign.handle_qa_artifact_presign),
        "qa.requirement.waive": (qa_requirement_waive.handle_qa_requirement_waive),
        "test_machine.case_execute": test_machine_case.handle_case_execute,
    }.get(function_id)


def _composed_call(
    parent: FunctionCallRequest,
    function_id: str,
    target: TargetRef,
    payload: dict[str, Any],
    actor: Optional[ActorContext],
) -> FunctionCallResponse:
    """Invoke one target-bound internal leg after parent authorization."""
    handler = _handler_for(function_id)
    if handler is None:
        return FunctionCallResponse(
            success=False,
            function=function_id,
            version="v1",
            error=FunctionError(
                code="composition_invalid",
                message=f"{function_id} is not a composed QA operation",
            ),
        )
    nested = FunctionCallRequest(
        function=function_id,
        actor=actor or parent.actor,
        target=target,
        payload=payload,
        intent=f"composed by {parent.function}",
    )
    outcome = handler(nested)
    return FunctionCallResponse(
        success=outcome.primary_success and outcome.error is None,
        function=function_id,
        version="v1",
        result=dict(outcome.result_payload),
        warnings=list(outcome.warnings),
        error=outcome.error,
        event_ids=list(outcome.handler_event_ids),
    )


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
        get_case_execution_context,
    )

    try:
        with connect() as conn:
            result = get_case_execution_context(
                conn,
                requirement_id=int(requirement_id),
            )
    except QaCaseExecutionError as exc:
        return _error("not_found", str(exc), "$.target.qa_requirement_id")
    return HandlerOutcome(
        result_payload={"case": result},
        primary_success=True,
    )


def handle_case_rerun(request: FunctionCallRequest) -> HandlerOutcome:
    requirement_id, invalid = _requirement_id(
        request,
        function_id="qa.case.rerun",
    )
    if invalid is not None:
        return invalid
    try:
        body = CaseRerunRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error("payload_invalid", str(exc), "$.payload")

    from functools import partial

    from yoke_core.domain.qa_case_execution import (
        QaCaseExecutionError,
        execute_case,
    )
    from yoke_core.domain.qa_composed_dispatch import composed_qa_dispatch

    try:
        with composed_qa_dispatch(partial(_composed_call, request)):
            result = execute_case(
                int(requirement_id),
                base_url=body.base_url,
                expected_branch=body.expected_branch,
                expected_sha=body.expected_sha,
                timeout_seconds=body.timeout_seconds,
                actor=request.actor,
            )
    except (QaCaseExecutionError, RuntimeError, ValueError, OSError) as exc:
        return _error("case_rerun_failed", str(exc), "$.target")
    return HandlerOutcome(primary_success=True, result_payload=result)


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
    "CaseRerunRequest",
    "CaseRerunResponse",
    "CaseWaiveRequest",
    "CaseWaiveResponse",
    "handle_case_execution_begin",
    "handle_case_rerun",
    "handle_case_waive",
]
