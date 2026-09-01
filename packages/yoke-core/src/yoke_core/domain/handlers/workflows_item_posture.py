"""Handler for amending one workflow-posture key on an existing item."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ItemPostureAmendRequest(BaseModel):
    key: str = Field(..., min_length=1)
    value: Any = None
    clear: bool = False
    reason: str = Field(..., min_length=1)


class ItemPostureAmendResponse(BaseModel):
    changed: bool
    item_id: int
    key: str
    before: Dict[str, Any]
    after: Dict[str, Any]
    waived_requirement_ids: List[int] = Field(default_factory=list)
    detached_plan_ids: List[int] = Field(default_factory=list)
    binding: Optional[Dict[str, Any]] = None
    event_id: Optional[str] = None


def _error(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def handle_item_posture_amend(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "item" or request.target.item_id is None:
        return _error(
            "target_invalid",
            "workflows.item_posture.amend requires a resolved item target",
            "$.target",
        )
    try:
        payload = ItemPostureAmendRequest.model_validate(request.payload or {})
    except ValueError as exc:
        return _error("payload_invalid", str(exc), "$.payload")
    from yoke_core.domain.actor_project_visibility import numeric_actor_id
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.item_posture_amend import amend_item_posture
    from yoke_core.domain.item_posture_amend_guards import ItemPostureAmendError

    actor = request.actor
    try:
        with connect() as conn:
            result = amend_item_posture(
                conn,
                item_id=int(request.target.item_id),
                key=payload.key,
                value=payload.value,
                clear=payload.clear,
                reason=payload.reason,
                actor_id=numeric_actor_id(actor.actor_id if actor else None),
                session_id=str((actor.session_id if actor else "") or ""),
            )
    except ItemPostureAmendError as exc:
        return _error("incompatible", str(exc), "$.payload.key")
    except LookupError as exc:
        return _error("not_found", str(exc), "$.target.item_id")
    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "ItemPostureAmendRequest",
    "ItemPostureAmendResponse",
    "handle_item_posture_amend",
]
