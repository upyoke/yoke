"""``doctor.last_run.get`` read handler: the most recent Doctor report.

Doctor results persist only as the ``YokeFunctionCalled`` journal
envelope of the ``doctor.run.run`` call; the scan, completeness rule
(``done: true`` only), and shrink-truncation honesty live in
:mod:`yoke_core.domain.last_doctor_run_read`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class DoctorLastRunGetRequest(BaseModel):
    project: Optional[str] = Field(
        default=None,
        description="Serve only a run recorded for this project (slug or id).",
    )


class DoctorLastRunGetResponse(BaseModel):
    never_run: bool = False
    ran_at: Optional[str] = None
    scope: Optional[str] = None
    project: Optional[str] = None
    pass_count: Optional[int] = None
    warn_count: Optional[int] = None
    fail_count: Optional[int] = None
    total: Optional[int] = None
    results: List[Dict[str, Any]] = Field(default_factory=list)
    truncated: bool = False


def handle_doctor_last_run_get(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}
    project = payload.get("project")
    if project is not None and not isinstance(project, str):
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="project must be a string when present",
                jsonpath="$.payload.project",
            ),
        )

    from yoke_core.domain.last_doctor_run_read import last_doctor_run

    try:
        result = last_doctor_run(project=project or None)
    except LookupError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="not_found",
                message=str(exc),
                jsonpath="$.payload.project",
            ),
        )
    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "DoctorLastRunGetRequest",
    "DoctorLastRunGetResponse",
    "handle_doctor_last_run_get",
]
