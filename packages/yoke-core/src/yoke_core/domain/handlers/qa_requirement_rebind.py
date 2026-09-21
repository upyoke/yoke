"""QA requirement execution-target rebind handler."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from yoke_core.domain.handlers.qa import _error
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)


class QaRequirementRebindTargetRequest(BaseModel):
    rationale: str = Field(..., min_length=1)


class QaRequirementRebindTargetResponse(BaseModel):
    requirement_id: int
    from_digest: str
    to_digest: str
    rebound_at: Optional[str] = None
    rebind_rationale: Optional[str] = None
    already_current: bool = False
    from_target: Optional[dict] = None
    endpoint_delta: Optional[dict] = None


def _actor_id(request: FunctionCallRequest) -> int | None:
    raw = getattr(request.actor, "actor_id", None)
    try:
        return int(raw) if raw is not None and str(raw).strip() else None
    except (TypeError, ValueError):
        return None


def handle_qa_requirement_rebind_target(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    req_id = request.target.qa_requirement_id
    if req_id is None:
        return _error(
            "target_invalid",
            "qa.requirement.rebind_target requires target.qa_requirement_id",
        )
    try:
        body = QaRequirementRebindTargetRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error("payload_invalid", f"rebind payload invalid: {exc}")

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_requirement_target_rebind import (
        QaRebindError,
        rebind_requirement,
    )

    conn = connect()
    try:
        try:
            result = rebind_requirement(
                conn,
                requirement_id=int(req_id),
                rationale=body.rationale,
                actor_id=_actor_id(request),
            )
        except LookupError as exc:
            return _error("not_found", str(exc))
        except QaRebindError as exc:
            return _error("rebind_refused", str(exc))
    finally:
        conn.close()

    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "QaRequirementRebindTargetRequest",
    "QaRequirementRebindTargetResponse",
    "handle_qa_requirement_rebind_target",
]
