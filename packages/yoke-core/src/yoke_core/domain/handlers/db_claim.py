"""Yoke function handler for ``db_claim.amend``.

Operation:

- ``db_claim.amend`` — apply a unified DB-claim amendment atomically.

Reuse: thin wrapper over :func:`yoke_core.domain.db_claim.amend`. All
validation (profile + attestation cross-field requirements, reserved
keys, atomic write) lives in the domain module; this handler only
translates envelope <-> domain types and back.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class AmendRequest(BaseModel):
    """Unified DB-claim amendment envelope payload.

    The ``claim`` dict is the unified payload documented in
    ``docs/db-reference/items-and-epics.md`` under "DB Claim — the
    unified amendment workflow." Both profile and attestation fields
    travel in a single dict; the domain layer demultiplexes and writes
    both stored fields atomically.
    """

    claim: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Unified claim payload combining db_mutation_profile and "
            "db_compatibility_attestation fields."
        ),
    )
    reason: str = Field(
        ..., min_length=1,
        description="Non-empty operator-facing justification.",
    )


class AmendResponse(BaseModel):
    item_id: int
    previous_profile: Dict[str, Any]
    previous_attestation: Dict[str, Any]
    new_profile: Dict[str, Any]
    new_attestation: Dict[str, Any]
    reason: str
    event_id: Optional[str] = None


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def handle_amend(request: FunctionCallRequest) -> HandlerOutcome:
    """Apply a unified DB-claim amendment for ``request.target.item_id``."""
    try:
        body = AmendRequest.model_validate(request.payload)
    except Exception as exc:
        return _err("payload_invalid", f"amend payload invalid: {exc}")

    item_id = request.target.item_id
    if item_id is None:
        return _err(
            "target_invalid",
            "db_claim.amend requires target.kind='item' with item_id set",
        )

    from yoke_core.domain.db_claim import DbClaimAmendmentError, amend

    try:
        result = amend(
            int(item_id),
            body.claim,
            reason=body.reason,
            session_id=request.actor.session_id,
        )
    except DbClaimAmendmentError as exc:
        return _err("amend_failed", str(exc))

    return HandlerOutcome(
        result_payload={
            "item_id": int(result.item_id),
            "previous_profile": dict(result.previous_profile),
            "previous_attestation": dict(result.previous_attestation),
            "new_profile": dict(result.new_profile),
            "new_attestation": dict(result.new_attestation),
            "reason": result.reason,
            "event_id": result.event_id,
        },
    )


__all__ = [
    "AmendRequest",
    "AmendResponse",
    "handle_amend",
]
