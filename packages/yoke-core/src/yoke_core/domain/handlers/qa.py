"""QA mutation handlers — qa.requirement.update and qa.run.record_verdict.

Both require ``claim_required_kind="item"`` so the dispatcher rejects calls
that lack an active claim on the target item. Companion module ``qa_run``
hosts ``qa.run.record_verdict`` so each file stays under the 350-line cap.

Domain reuse:

- Field allowlist for requirement-update mirrors
  :data:`yoke_core.domain.qa_requirement_ops.UPDATABLE_REQUIREMENT_FIELDS`.
- Enum constants come from :mod:`yoke_core.domain.qa_constants`.
- Event emission goes through :func:`qa_events.emit_qa_requirement_event`.

The CLI counterparts (`cmd_requirement_update`, `cmd_run_complete`) exit
on validation failure; handlers return a structured ``FunctionError`` instead.
"""

from __future__ import annotations

from typing import Any, Optional

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


def _error(
    code: str, message: str, *, jsonpath: Optional[str] = None
) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def handle_qa_requirement_update(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect, query_one
    from yoke_core.domain.qa_constants import (
        VALID_BLOCKING_MODES,
        VALID_QA_PHASES,
        _normalize_qa_phase,
    )
    from yoke_core.domain.qa_events import emit_qa_requirement_event
    from yoke_core.domain.qa_requirement_ops import UPDATABLE_REQUIREMENT_FIELDS

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
    if field == "qa_kind":
        return _error(
            "field_not_updatable",
            "qa_kind is not updatable; use requirement-waive + requirement-add",
            jsonpath="$.payload.field",
        )
    if field not in UPDATABLE_REQUIREMENT_FIELDS:
        return _error(
            "field_not_updatable",
            f"field {field!r} is not updatable; allowed: "
            f"{', '.join(UPDATABLE_REQUIREMENT_FIELDS)}",
            jsonpath="$.payload.field",
        )

    if field == "blocking_mode" and value not in VALID_BLOCKING_MODES:
        return _error(
            "payload_invalid",
            f"blocking_mode must be one of {sorted(VALID_BLOCKING_MODES)}",
            jsonpath="$.payload.value",
        )
    if field == "qa_phase":
        normalized = _normalize_qa_phase(str(value or ""))
        if normalized not in VALID_QA_PHASES:
            return _error(
                "payload_invalid",
                f"qa_phase must be one of {sorted(VALID_QA_PHASES)}",
                jsonpath="$.payload.value",
            )
        value = normalized
    if field == "capability_requirements":
        from yoke_core.domain.qa_method_capabilities import (
            QaMethodCapabilityError,
            encoded_capability_kinds,
        )

        try:
            value = encoded_capability_kinds(value, subject="QA requirement")
        except QaMethodCapabilityError as exc:
            return _error(
                "payload_invalid",
                str(exc),
                jsonpath="$.payload.value",
            )

    conn = connect()
    try:
        p = _p(conn)
        existing = query_one(
            conn,
            "SELECT qa_kind, qa_phase, item_id, epic_id, task_num, "
            f"deployment_run_id FROM qa_requirements WHERE id = {p}",
            (int(req_id),),
        )
        if existing is None:
            return _error("not_found", f"requirement {req_id} not found")
        p = _p(conn)
        conn.execute(
            f"UPDATE qa_requirements SET {field} = {p} WHERE id = {p}",
            (value, int(req_id)),
        )
        conn.commit()
        event_phase = value if field == "qa_phase" else str(existing["qa_phase"])
        emit_qa_requirement_event(
            conn,
            db_path=None,
            event_name="QARequirementUpdated",
            requirement_id=int(req_id),
            qa_kind=str(existing["qa_kind"]),
            qa_phase=event_phase,
            extra_detail={"field": field, "new_value": value},
            target_row=existing,
        )
    finally:
        conn.close()

    return HandlerOutcome(
        result_payload={
            "requirement_id": int(req_id),
            "field": field,
            "new_value": value,
        },
        primary_success=True,
    )


__all__ = [
    "QaRequirementUpdateRequest",
    "QaRequirementUpdateResponse",
    "handle_qa_requirement_update",
    "_error",
]
