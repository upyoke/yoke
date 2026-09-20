"""QA requirement supersession handler."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from yoke_core.domain.handlers.qa import _error
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)


class QaRequirementSupersedeRequest(BaseModel):
    superseded_by_requirement_id: int = Field(..., gt=0)
    rationale: str = Field(..., min_length=1)
    source: str = "agent"


class QaRequirementSupersedeResponse(BaseModel):
    requirement_id: int
    superseded_by_requirement_id: int
    superseded_at: str
    supersession_rationale: str
    supersession_source: str
    #: Present only when the discharged row was an admitted copy whose intake
    #: requirement is still outstanding, because supersession is run-local and
    #: the next release admits that row again untouched.
    admitted_from_requirement_id: Optional[int] = None
    next_admission_notice: Optional[str] = None


def handle_qa_requirement_supersede(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    target = request.target
    req_id: Optional[int] = target.qa_requirement_id
    if req_id is None:
        return _error(
            "target_invalid",
            "qa.requirement.supersede requires target.qa_requirement_id",
        )
    try:
        body = QaRequirementSupersedeRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error("payload_invalid", f"supersede payload invalid: {exc}")

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_requirement_supersession import (
        QaSupersessionError,
        supersede_requirement,
    )

    conn = connect()
    try:
        try:
            result = supersede_requirement(
                conn,
                requirement_id=int(req_id),
                superseded_by_requirement_id=int(body.superseded_by_requirement_id),
                rationale=body.rationale,
                source=body.source,
            )
        except LookupError as exc:
            return _error("not_found", str(exc))
        except QaSupersessionError as exc:
            return _error("supersession_refused", str(exc))
    finally:
        conn.close()

    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "QaRequirementSupersedeRequest",
    "QaRequirementSupersedeResponse",
    "handle_qa_requirement_supersede",
]
