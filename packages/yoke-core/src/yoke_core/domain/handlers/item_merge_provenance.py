"""Operator-facing repair of a terminal item's unset merge timestamp.

Thin dispatcher wrapper over
:func:`yoke_core.domain.item_merge_provenance_operator.operator_correct_merged_at`,
which owns every guardrail (hook-context refusal, required operator reason,
terminal-stage requirement, unset-value requirement, timestamp validation)
and the ledger-first WARN event.

Unlike the claim-free finalize writes in
:mod:`yoke_core.domain.handlers.done_transition_writes`, this surface is
``adapter_status='wrapped'``: it is the named human escape hatch the
terminal-immutability contract points at, so it needs a CLI adapter. It
stays claim-free because a terminal item cannot be claimed at all -- the
operator reason and the WARN event are the accountability record instead.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)

from yoke_core.domain.item_merge_provenance_operator import (
    MergedAtCorrectionError,
    MergedAtCorrectionHookContextError,
    operator_correct_merged_at,
)


class OperatorCorrectMergedAtRequest(BaseModel):
    merged_at: str = Field(..., min_length=1)
    operator_reason: str = Field(..., min_length=1)


class OperatorCorrectMergedAtResponse(BaseModel):
    corrected: bool
    item_id: int
    public_ref: str
    status: str
    merged_at: str
    operator_reason: str
    operator_session_id: str


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def _require_item_id(request: FunctionCallRequest) -> Optional[int]:
    if request.target.item_id is None:
        return None
    return int(request.target.item_id)


def handle_operator_correct_merged_at(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """Fill a terminal item's unset ``items.merged_at`` under operator authority."""
    item_id = _require_item_id(request)
    if item_id is None:
        return _err(
            "target_invalid",
            "operator_correct_merged_at requires target.item_id",
        )
    try:
        body = OperatorCorrectMergedAtRequest.model_validate(request.payload)
    except ValidationError as exc:
        return _err(
            "payload_invalid",
            f"operator_correct_merged_at payload invalid: {exc}",
        )

    session_id = request.actor.session_id if request.actor is not None else None

    try:
        with _connect_rw() as conn:
            result = operator_correct_merged_at(
                conn,
                item_id,
                body.merged_at,
                body.operator_reason,
                session_id=session_id,
            )
    except MergedAtCorrectionHookContextError as exc:
        return _err("hook_context_refused", str(exc))
    except MergedAtCorrectionError as exc:
        return _err("merged_at_correction_refused", str(exc))
    except Exception as exc:  # noqa: BLE001 - surfaced so the caller aborts
        return _err("merged_at_correction_failed", str(exc))

    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "OperatorCorrectMergedAtRequest",
    "OperatorCorrectMergedAtResponse",
    "handle_operator_correct_merged_at",
]
