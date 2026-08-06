"""Build the dispatcher claim-verification event snapshot.

The dispatcher passes one mutable mapping through claim verification and
persists it only after the handler returns.  Values in the mapping are
therefore observations from the pre-handler authorization boundary, not a
reconstruction from claim state after a handler may have released it.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_core.domain.yoke_function_registry import RegistryEntry


ClaimVerificationEvidence = Dict[str, Any]
CLAIM_VERIFICATION_ALLOWED = "allowed"
CLAIM_VERIFICATION_PHASE = "pre_handler"
WORK_CLAIM_AUTHORITY = "work_claim"


def begin_claim_verification(
    evidence: Optional[ClaimVerificationEvidence],
    entry: RegistryEntry,
    request: FunctionCallRequest,
) -> None:
    """Seed evidence before the registry-directed claim check runs."""
    if evidence is None:
        return
    target = request.target
    evidence.update(
        {
            "phase": CLAIM_VERIFICATION_PHASE,
            "required_kind": entry.claim_required_kind,
            "decision": (
                "not_required"
                if entry.claim_required_kind is None
                else "pending"
            ),
            "caller_session_id": request.actor.session_id,
            "target_kind": target.kind,
        }
    )
    if target.item_id is not None:
        evidence["target_item_id"] = int(target.item_id)
    if target.epic_id is not None:
        evidence["target_epic_id"] = int(target.epic_id)


def allow_claim_verification(
    evidence: Optional[ClaimVerificationEvidence],
    *,
    authority: str,
    target_item_id: Optional[int] = None,
    target_epic_id: Optional[int] = None,
    claim_id: Any = None,
    holder_session_id: Optional[str] = None,
) -> None:
    """Record the authority facts used by a successful claim check."""
    if evidence is None:
        return
    evidence.update({"decision": CLAIM_VERIFICATION_ALLOWED, "authority": authority})
    if target_item_id is not None:
        evidence["target_item_id"] = int(target_item_id)
    if target_epic_id is not None:
        evidence["target_epic_id"] = int(target_epic_id)
    if claim_id is not None:
        evidence["claim_id"] = int(claim_id)
    if holder_session_id:
        evidence["holder_session_id"] = str(holder_session_id)


__all__ = [
    "ClaimVerificationEvidence",
    "CLAIM_VERIFICATION_ALLOWED",
    "CLAIM_VERIFICATION_PHASE",
    "WORK_CLAIM_AUTHORITY",
    "allow_claim_verification",
    "begin_claim_verification",
]
