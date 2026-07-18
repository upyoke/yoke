"""Atomic registered dispatch-chain advancement."""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ChainAdvanceRequest(BaseModel):
    worktree: str = Field(..., min_length=1)


class ChainAdvanceResponse(BaseModel):
    epic_id: int
    current_index: int
    next_task_num: int


def _error(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def handle_dispatch_chain_advance(request: FunctionCallRequest) -> HandlerOutcome:
    target = request.target
    if target.kind != "epic_task" or target.epic_id is None:
        return _error("invalid_payload", "target must carry epic_id")
    try:
        payload = ChainAdvanceRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error("invalid_payload", f"payload invalid: {exc}")
    from yoke_core.domain import db_helpers, epic

    with db_helpers.connect() as conn:
        try:
            raw = epic.dispatch_chain_advance(
                conn, str(target.epic_id), payload.worktree,
            )
        except LookupError as exc:
            return _error("target_not_found", str(exc))
        except (IndexError, ValueError) as exc:
            return _error("invalid_payload", str(exc))
    current_index, next_task_num = raw.split("|", 1)
    return HandlerOutcome(
        result_payload=ChainAdvanceResponse(
            epic_id=int(target.epic_id),
            current_index=int(current_index),
            next_task_num=int(next_task_num),
        ).model_dump(),
        primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [{
    "function_id": "workflow_item.epic_dispatch_chain.advance",
    "handler": handle_dispatch_chain_advance,
    "request_model": ChainAdvanceRequest,
    "response_model": ChainAdvanceResponse,
    "stability": "stable",
    "owner_module": (
        "yoke_core.domain.handlers.workflow_item_epic_dispatch_advance"
    ),
    "target_kinds": ["epic_task"],
    "side_effects": ["epic_dispatch_chains_update"],
    "emitted_event_names": ["YokeFunctionCalled"],
    "guardrails": [],
    "adapter_status": "live",
    "claim_required_kind": "epic",
}]


__all__ = ["REGISTRATIONS", "handle_dispatch_chain_advance"]
