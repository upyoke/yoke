"""QA requirement waiver handler."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from yoke_core.domain.handlers.qa import _error
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)


class QaRequirementWaiveRequest(BaseModel):
    rationale: str = Field(..., min_length=1)
    source: str = "agent"
    force: bool = False


class QaRequirementWaiveResponse(BaseModel):
    requirement_id: int
    source: str
    waived: bool


def handle_qa_requirement_waive(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    target = request.target
    req_id: Optional[int] = target.qa_requirement_id
    if req_id is None:
        return _error(
            "target_invalid",
            "qa.requirement.waive requires target.qa_requirement_id",
        )
    try:
        body = QaRequirementWaiveRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error("payload_invalid", f"waive payload invalid: {exc}")
    if body.source not in {"agent", "operator"}:
        return _error(
            "payload_invalid",
            "source must be one of ['agent', 'operator']",
            jsonpath="$.payload.source",
        )

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_requirement_ops import waive_requirement

    conn = connect()
    try:
        try:
            waive_requirement(
                conn,
                int(req_id),
                body.rationale,
                source=body.source,
                force=bool(body.force),
            )
        except LookupError as exc:
            return _error("not_found", str(exc))
        except PermissionError as exc:
            return _error("force_required", str(exc), jsonpath="$.payload.force")
    finally:
        conn.close()

    return HandlerOutcome(
        result_payload={
            "requirement_id": int(req_id),
            "source": body.source,
            "waived": True,
        },
        primary_success=True,
    )


__all__ = [
    "QaRequirementWaiveRequest",
    "QaRequirementWaiveResponse",
    "handle_qa_requirement_waive",
]
