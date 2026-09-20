"""QA mutation handlers — qa.requirement.update and qa.run.record_verdict.

Both require ``claim_required_kind="item"`` so the dispatcher rejects calls
that lack an active claim on the target item. Companion module ``qa_run``
hosts ``qa.run.record_verdict`` so each file stays under the 350-line cap.

Domain reuse:

- Field allowlist and mutation live in
  :mod:`yoke_core.domain.qa_requirement_config_update`.

The CLI counterparts (`cmd_requirement_update`, `cmd_run_complete`) exit
on validation failure; handlers return a structured ``FunctionError`` instead.
"""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel

from yoke_core.domain import db_backend
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


# ---------------------------------------------------------------------------
# qa.requirement.update.run
# ---------------------------------------------------------------------------


class QaRequirementUpdateRequest(BaseModel):
    field: str
    value: Optional[str] = None


class QaRequirementUpdateResponse(BaseModel):
    requirement_id: int
    field: str
    new_value: Optional[str] = None
    #: Admitted deployment-stage copies this amendment also reached, so the
    #: caller learns a run in flight was corrected rather than left behind.
    admitted_copies_updated: List[int] = []


def _error(
    code: str, message: str, *, jsonpath: Optional[str] = None
) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def handle_qa_requirement_update(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_requirement_config_update import apply_requirement_update

    target = request.target
    req_id = target.qa_requirement_id
    if req_id is None:
        return _error(
            "target_invalid",
            "qa.requirement.update requires target.qa_requirement_id",
        )
    payload = request.payload or {}
    field = payload.get("field")
    value = payload.get("value")
    if not isinstance(field, str) or not field:
        return _error(
            "payload_invalid",
            "field is required",
            jsonpath="$.payload.field",
        )

    conn = connect()
    try:
        result = apply_requirement_update(conn, int(req_id), field, value)
    finally:
        conn.close()
    if not result.ok:
        return _error(
            result.error_code,
            result.message,
            jsonpath=result.jsonpath,
        )
    return HandlerOutcome(
        result_payload={
            "requirement_id": result.requirement_id,
            "field": result.field,
            "new_value": result.new_value,
            "admitted_copies_updated": list(result.admitted_copies_updated),
        },
        primary_success=True,
    )


__all__ = [
    "QaRequirementUpdateRequest",
    "QaRequirementUpdateResponse",
    "handle_qa_requirement_update",
    "_error",
]
