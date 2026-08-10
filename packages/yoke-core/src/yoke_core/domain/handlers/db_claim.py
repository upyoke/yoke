"""Yoke function handlers for ``db_claim.*``.

Operations:

- ``db_claim.amend`` — apply a unified DB-claim amendment atomically.
- ``db_claim.prose_check`` — prose-vs-claim detector over a stored item
  (https-relayable read; replaces local-only ``python3 -m … check-item``).

Reuse: thin wrappers over :func:`yoke_core.domain.db_claim.amend` and
:func:`yoke_core.domain.db_claim_prose_check.check_item`. All validation
and detection live in the domain modules; these handlers only translate
envelope <-> domain types and back.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class AmendRequest(BaseModel):
    """Unified DB-claim amendment envelope payload.

    The ``claim`` dict is the unified payload documented in
    ``.yoke/docs/reference/db-reference/items-and-epics.md`` under "DB Claim — the
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


class ProseCheckRequest(BaseModel):
    """Empty payload — the item target carries the identity."""


class ProseCheckResponse(BaseModel):
    item_id: int
    blocks: bool
    triggers: List[str] = Field(default_factory=list)
    has_declared_claim: bool = False
    negative_claim_detected: bool = False
    reviewed_negative_claim_detected: bool = False
    matched_snippets: List[str] = Field(default_factory=list)
    recovery: str = ""


def handle_prose_check(request: FunctionCallRequest) -> HandlerOutcome:
    """Run the prose-vs-claim detector for ``request.target.item_id``."""
    try:
        ProseCheckRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _err("payload_invalid", f"prose_check payload invalid: {exc}")

    item_id = request.target.item_id
    if item_id is None:
        return _err(
            "target_invalid",
            "db_claim.prose_check requires target.kind='item' with item_id set",
        )

    from yoke_core.domain.db_claim_prose_check import check_item

    outcome = check_item(int(item_id))
    return HandlerOutcome(
        result_payload={
            "item_id": int(item_id),
            "blocks": bool(outcome.blocks),
            "triggers": list(outcome.triggers),
            "has_declared_claim": bool(outcome.has_declared_claim),
            "negative_claim_detected": bool(outcome.negative_claim_detected),
            "reviewed_negative_claim_detected": bool(
                outcome.reviewed_negative_claim_detected
            ),
            "matched_snippets": list(outcome.matched_snippets),
            "recovery": outcome.recovery,
        },
    )


__all__ = [
    "AmendRequest",
    "AmendResponse",
    "ProseCheckRequest",
    "ProseCheckResponse",
    "handle_amend",
    "handle_prose_check",
]
