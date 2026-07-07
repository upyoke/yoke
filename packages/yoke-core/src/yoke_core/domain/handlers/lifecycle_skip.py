"""Handler for the ``lifecycle.skip.record_recoverable_substrate`` function id.

Wraps :func:`yoke_core.domain.sessions_handler_outcome.record_recoverable_substrate_skip`
so the documented ``/yoke do`` Step B recipe ("first record the skip
through ...") has an agent-executable shape. The previous recipe pointed
at a ``python3 -c "from yoke_core.domain... import ..."`` form that the
``lint-no-agent-runtime-api-import-from-c`` PreToolUse hook refuses
outright — leaving every chain that hit a recoverable substrate
failure unable to follow its own teaching surface.

The handler accepts the same parameters the helper takes, opens the
control-plane DB connection via :mod:`yoke_core.domain.db_helpers`,
and forwards the call. The returned ``chain_skip_memory`` entry rides
back on ``HandlerOutcome.result_payload`` so the CLI surface and any
in-process caller see the same persisted entry.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_core.domain.sessions_handler_outcome import (
    record_recoverable_substrate_skip,
)
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class LifecycleSkipRecordRecoverableSubstrateRequest(BaseModel):
    """Payload for ``lifecycle.skip.record_recoverable_substrate``."""

    chain_step: int = Field(
        ..., description="Current /yoke do chain step number."
    )
    project: str = Field(
        ...,
        description=(
            "Project id the failing handler is bound to (e.g. ``yoke``). "
            "Rides through to the ``SchedulerOfferSkipped`` event context."
        ),
    )
    routed_action: str = Field(
        ..., description="Routed action that failed (e.g. ``advance``)."
    )
    failure_class: str = Field(
        ...,
        description=(
            "Structured failure class string the handler reports. Surfaces "
            "in the chain-skip-memory entry and the audit event."
        ),
    )
    remediation_owner: str = Field(
        ...,
        description=(
            "Ticket id or recipe owner responsible for the fix "
            "(e.g. ``YOK-N``)."
        ),
    )
    current_status: Optional[str] = Field(
        default=None,
        description="Lifecycle status of the failing item at skip time.",
    )
    useful_work_began: bool = Field(
        default=False,
        description=(
            "Whether the routed handler made any useful progress before the "
            "substrate failure. ``False`` is the canonical case for the "
            "/yoke do loop's no-progress detection."
        ),
    )


class LifecycleSkipRecordRecoverableSubstrateResponse(BaseModel):
    """Successful result envelope mirroring the persisted skip entry."""

    skip_reason: str
    chain_step: int
    routed_action: str
    failure_class: str
    remediation_owner: str
    useful_work_began: bool
    item_id: Optional[str] = None
    current_status: Optional[str] = None


def _error_outcome(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def handle_record_recoverable_substrate_skip(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """Forward the recoverable-substrate skip recording call to the helper."""
    target = request.target
    if target.kind != "item" or target.item_id is None:
        return _error_outcome(
            "invalid_payload",
            "lifecycle.skip.record_recoverable_substrate target must carry "
            "kind='item' + item_id.",
        )
    try:
        payload = LifecycleSkipRecordRecoverableSubstrateRequest.model_validate(
            request.payload,
        )
    except Exception as exc:
        return _error_outcome("invalid_payload", f"payload invalid: {exc}")

    item_id_str = f"YOK-{int(target.item_id)}"

    from yoke_core.domain import db_helpers

    with db_helpers.connect() as conn:
        entry: Dict[str, Any] = record_recoverable_substrate_skip(
            conn,
            session_id=request.actor.session_id,
            chain_step=payload.chain_step,
            project=payload.project,
            item_id=item_id_str,
            routed_action=payload.routed_action,
            failure_class=payload.failure_class,
            remediation_owner=payload.remediation_owner,
            current_status=payload.current_status,
            useful_work_began=payload.useful_work_began,
        )

    response = LifecycleSkipRecordRecoverableSubstrateResponse(
        skip_reason=str(entry.get("skip_reason", "recoverable_substrate")),
        chain_step=int(entry.get("chain_step", payload.chain_step)),
        routed_action=str(entry.get("routed_action", payload.routed_action)),
        failure_class=str(entry.get("failure_class", payload.failure_class)),
        remediation_owner=str(
            entry.get("remediation_owner", payload.remediation_owner)
        ),
        useful_work_began=bool(
            entry.get("useful_work_began", payload.useful_work_began)
        ),
        item_id=entry.get("item_id"),
        current_status=entry.get("current_status", payload.current_status),
    )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "lifecycle.skip.record_recoverable_substrate",
        "handler": handle_record_recoverable_substrate_skip,
        "request_model": LifecycleSkipRecordRecoverableSubstrateRequest,
        "response_model": LifecycleSkipRecordRecoverableSubstrateResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.lifecycle_skip",
        "target_kinds": ["item"],
        "side_effects": [
            "append_chain_skip_memory",
            "release_item_claim_for_execution",
            "emit_scheduler_offer_skipped",
        ],
        "emitted_event_names": [
            "YokeFunctionCalled",
            "SchedulerOfferSkipped",
        ],
        "guardrails": ["claim_required"],
        "adapter_status": "live",
        "claim_required_kind": "item",
    },
]


__all__ = [
    "handle_record_recoverable_substrate_skip",
    "LifecycleSkipRecordRecoverableSubstrateRequest",
    "LifecycleSkipRecordRecoverableSubstrateResponse",
    "REGISTRATIONS",
]
