"""Handler for idempotent field-note promotion into a Dash."""

from __future__ import annotations

from typing import Any, List, Mapping, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.field_note_dash_promotion import (
    FieldNotePromotionError,
    FieldNotePromotionInProgress,
    promote_field_note_to_dash,
)


class PromoteRequest(BaseModel):
    entry_id: int = Field(..., gt=0)
    title: str = Field(..., min_length=1, max_length=100)
    instruction: Optional[str] = None
    project: Optional[str] = None
    priority: Optional[str] = None
    workflow_posture: Mapping[str, Any] = Field(default_factory=dict)


class PromoteResponse(BaseModel):
    entry_id: int
    dash_item_id: int
    dash_item_ref: str
    created: bool


def _error(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def handle_promote(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "global":
        return _error("invalid_target", "target.kind must be 'global'")
    try:
        payload = PromoteRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error("invalid_payload", f"payload invalid: {exc}")
    raw_actor = request.actor.actor_id
    actor_id = (
        int(raw_actor)
        if raw_actor is not None and str(raw_actor).isdigit()
        else None
    )
    from yoke_core.domain.db_helpers import connect
    with connect() as conn:
        try:
            result = promote_field_note_to_dash(
                conn,
                entry_id=payload.entry_id,
                title=payload.title,
                instruction=payload.instruction,
                project=payload.project,
                priority=payload.priority,
                workflow_posture=payload.workflow_posture,
                actor_id=actor_id,
                session_id=request.actor.session_id,
            )
        except FieldNotePromotionInProgress as exc:
            return _error("promotion_in_progress", str(exc))
        except FieldNotePromotionError as exc:
            return _error("promotion_refused", str(exc))
    return HandlerOutcome(
        result_payload=PromoteResponse(
            entry_id=result.entry_id,
            dash_item_id=result.dash_item_id,
            dash_item_ref=result.dash_item_ref,
            created=result.created,
        ).model_dump(),
    )


REGISTRATIONS: List[dict[str, Any]] = [
    {
        "function_id": "ouroboros.field_note.promote",
        "handler": handle_promote,
        "request_model": PromoteRequest,
        "response_model": PromoteResponse,
        "stability": "stable",
        "owner_module": (
            "yoke_core.domain.handlers.field_note_dash_promotion"
        ),
        "target_kinds": ["global"],
        "side_effects": ["item_insert", "db_write", "github_sync"],
        "emitted_event_names": ["YokeFunctionCalled"],
        "guardrails": ["promotion_idempotency", "workflow_entry_surface"],
        "adapter_status": "live",
        "claim_required_kind": None,
    },
]


__all__ = [
    "PromoteRequest",
    "PromoteResponse",
    "REGISTRATIONS",
    "handle_promote",
]
