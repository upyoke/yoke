"""Yoke function handlers for path-claim activation + coordination decision.

Separated from :mod:`claims_path` so each handler module stays under the
350-line file budget. Operations:

- ``claims.path.required_gate`` — evaluate the idea/refine coverage gate.
- ``claims.path.activation_run`` — run the activation phase for an item.
- ``claims.path.coordination_decision.build`` — build the LLM evidence
  packet for an authored coordination decision (read-only).

Reuse: thin wrappers over
:mod:`yoke_core.domain.advance_path_claim_activation` and
:mod:`yoke_core.domain.path_claim_coordination_decision`.
"""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class RequiredGateRequest(BaseModel):
    item_id: Optional[int] = None


class RequiredGateResponse(BaseModel):
    verdict: str
    reason: str
    satisfying_claims: List[int] = Field(default_factory=list)


class ActivationRunRequest(BaseModel):
    item_id: Optional[int] = None
    actor_id: Optional[int] = None


class ActivationOutcomeRow(BaseModel):
    claim_id: int
    state_before: str
    state_after: str
    error: Optional[str] = None


class ActivationRunResponse(BaseModel):
    item_id: int
    actor_id: int
    outcomes: List[ActivationOutcomeRow] = Field(default_factory=list)
    blocked_errors: List[str] = Field(default_factory=list)
    diverged_error: Optional[str] = None


class CoordinationDecisionBuildRequest(BaseModel):
    candidate_item_id: Optional[int] = None
    conflicting_claim_id: int
    shared_paths: List[str] = Field(default_factory=list)


class CoordinationDecisionBuildResponse(BaseModel):
    context: dict


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers
    return db_helpers.connect()


def _resolved_item_id(request: FunctionCallRequest, payload_item_id: object) -> int:
    if payload_item_id is not None:
        return int(payload_item_id)
    if request.target.item_id is not None:
        return int(request.target.item_id)
    raise ValueError("resolved item target required")


def _resolved_actor_id(request: FunctionCallRequest, payload_actor_id: object) -> int:
    raw = payload_actor_id if payload_actor_id is not None else request.actor.actor_id
    if raw is None or str(raw).strip() == "":
        raise ValueError("resolved actor_id required for activation")
    return int(raw)


def handle_required_gate(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = RequiredGateRequest.model_validate(request.payload)
        item_id = _resolved_item_id(request, body.item_id)
    except Exception as exc:
        return _err("payload_invalid", f"required_gate payload invalid: {exc}")

    from yoke_core.domain.path_claim_required_gate import evaluate

    with _connect_rw() as conn:
        result = evaluate(conn, item_id)
    return HandlerOutcome(result_payload=dict(result), primary_success=True)


def handle_activation_run(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = ActivationRunRequest.model_validate(request.payload)
        item_id = _resolved_item_id(request, body.item_id)
        actor_id = _resolved_actor_id(request, body.actor_id)
    except Exception as exc:
        return _err("payload_invalid", f"activation.run payload invalid: {exc}")

    from yoke_core.domain.advance_path_claim_activation import (
        run_activation_phase,
    )

    with _connect_rw() as conn:
        result = run_activation_phase(
            conn,
            item_id=item_id,
            actor_id=actor_id,
            session_id=request.actor.session_id,
        )

    return HandlerOutcome(
        result_payload={
            "item_id": item_id,
            "outcomes": [
                {
                    "claim_id": o.claim_id,
                    "state_before": o.state_before,
                    "state_after": o.state_after,
                    "error": o.error,
                }
                for o in result.outcomes
            ],
            "actor_id": actor_id,
            "blocked_errors": list(result.blocked_errors),
            "diverged_error": result.diverged_error,
        },
    )


def handle_coordination_decision_build(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        body = CoordinationDecisionBuildRequest.model_validate(request.payload)
        candidate_item_id = _resolved_item_id(request, body.candidate_item_id)
    except Exception as exc:
        return _err(
            "payload_invalid",
            f"coordination_decision.build payload invalid: {exc}",
        )

    from yoke_core.domain.path_claim_coordination_decision import (
        build_coordination_context,
    )

    with _connect_rw() as conn:
        try:
            ctx = build_coordination_context(
                conn,
                candidate_item_id=candidate_item_id,
                conflicting_claim_id=int(body.conflicting_claim_id),
                shared_paths=list(body.shared_paths),
            )
        except Exception as exc:
            return _err("build_failed", f"{type(exc).__name__}: {exc}")

    return HandlerOutcome(result_payload={"context": dict(ctx)})


__all__ = [
    "RequiredGateRequest",
    "RequiredGateResponse",
    "ActivationRunRequest",
    "ActivationRunResponse",
    "ActivationOutcomeRow",
    "CoordinationDecisionBuildRequest",
    "CoordinationDecisionBuildResponse",
    "handle_required_gate",
    "handle_activation_run",
    "handle_coordination_decision_build",
]
