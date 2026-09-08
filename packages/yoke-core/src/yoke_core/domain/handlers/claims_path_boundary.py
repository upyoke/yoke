"""Registered transport boundary for caller-produced path-claim proofs."""

from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class BoundaryContextRequest(BaseModel):
    pass


class BoundaryContextResponse(BaseModel):
    context: Dict[str, Any]


class BoundaryObserveRequest(BaseModel):
    context: Dict[str, Any] = Field(default_factory=dict)
    repo_path: str


class BoundaryObserveResponse(BaseModel):
    proof: Dict[str, Any]


class BoundaryProveRequest(BaseModel):
    proof: Dict[str, Any] = Field(default_factory=dict)


class BoundaryProveResponse(BaseModel):
    item_id: int
    rung_id: str
    lane_commit_sha: str


def _error(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _item_id(request: FunctionCallRequest) -> int:
    if request.target.kind != "item" or request.target.item_id is None:
        raise ValueError("an item target is required")
    return int(request.target.item_id)


def handle_boundary_context(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        BoundaryContextRequest.model_validate(request.payload or {})
        item_id = _item_id(request)
    except Exception as exc:
        return _error("payload_invalid", f"boundary context invalid: {exc}")

    from yoke_core.domain import db_helpers
    from yoke_core.domain.path_claim_boundary_gate_proof import (
        BoundaryProofError,
        boundary_context,
    )

    with db_helpers.connect() as conn:
        try:
            context = boundary_context(conn, item_id)
        except BoundaryProofError as exc:
            return _error("boundary_context_unavailable", str(exc))
    return HandlerOutcome(result_payload={"context": context})


def handle_boundary_observe(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = BoundaryObserveRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error("payload_invalid", f"boundary observation invalid: {exc}")

    from yoke_core.domain.path_claim_boundary_gate_proof import (
        BoundaryProofError,
        build_local_boundary_proof,
    )

    try:
        proof = build_local_boundary_proof(body.context, body.repo_path)
    except BoundaryProofError as exc:
        return _error("boundary_proof_failed", str(exc))
    return HandlerOutcome(result_payload={"proof": proof})


def handle_boundary_prove(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = BoundaryProveRequest.model_validate(request.payload or {})
        item_id = _item_id(request)
    except Exception as exc:
        return _error("payload_invalid", f"boundary proof invalid: {exc}")

    from yoke_core.domain import db_helpers
    from yoke_core.domain.path_claim_boundary_gate_proof import (
        BoundaryProofError,
        record_boundary_proof,
    )

    with db_helpers.connect() as conn:
        try:
            proof = record_boundary_proof(
                conn,
                item_id=item_id,
                session_id=request.actor.session_id or "",
                proof=body.proof,
            )
        except BoundaryProofError as exc:
            return _error("boundary_proof_refused", str(exc))
    lane = proof["lane"]
    return HandlerOutcome(
        result_payload={
            "item_id": item_id,
            "rung_id": str(proof["rung_id"]),
            "lane_commit_sha": str(lane["commit_sha"]),
        }
    )


__all__ = [
    "BoundaryContextRequest",
    "BoundaryContextResponse",
    "BoundaryObserveRequest",
    "BoundaryObserveResponse",
    "BoundaryProveRequest",
    "BoundaryProveResponse",
    "handle_boundary_context",
    "handle_boundary_observe",
    "handle_boundary_prove",
]
