"""Yoke function handlers for path-claim activation + coordination decision.

Separated from :mod:`claims_path` so each handler module stays under the
350-line file budget. Operations:

- ``claims.path.required_gate`` — evaluate the idea/refine coverage gate.
- ``claims.path.activation_run`` — run the activation phase for an item.
- ``claims.path.survey_ensure`` — register/widen a selected-Dash path
  claim from its live conflict survey.
- ``claims.path.coordination_decision.build`` — build the LLM evidence
  packet for an authored coordination decision (read-only).

Reuse: thin wrappers over
:mod:`yoke_core.domain.advance_path_claim_activation`,
:mod:`yoke_core.domain.dash_path_claim_posture`, and
:mod:`yoke_core.domain.path_claim_coordination_decision`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

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
    resolved_heads: Optional[Dict[int, str]] = None


class SurveyEnsureRequest(BaseModel):
    item_id: Optional[int] = None
    touch_paths: List[str] = Field(default_factory=list)
    integration_target: str = "main"


class SurveyEnsureResponse(BaseModel):
    claim_id: Optional[int] = None


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
    except Exception as exc:
        return _err("payload_invalid", f"activation.run payload invalid: {exc}")

    from yoke_core.domain.advance_path_claim_activation import (
        check_work_claim_ownership,
        resolve_item_actor,
        run_activation_phase,
    )

    with _connect_rw() as conn:
        # Resolve the item's owning actor (the actor its path claims are
        # attributed to). An explicit payload actor_id is honored as an
        # operator/debug override; the transport-aware preflight does not
        # supply one, so the COALESCE(owner, source) resolution is the
        # normal path. Fold in the standalone-activation ownership guard:
        # refuse when another live session holds the item work claim.
        if body.actor_id is not None:
            actor_id = int(body.actor_id)
        else:
            actor_id, actor_error = resolve_item_actor(conn, item_id)
            if actor_error is not None:
                return _err("actor_unavailable", actor_error)
        other_session = check_work_claim_ownership(
            conn,
            item_id=item_id,
            session_id=request.actor.session_id or "",
        )
        if other_session:
            return _err(
                "work_claim_conflict",
                f"work claim for item {item_id} held by session "
                f"'{other_session}'; activation refused to avoid stranded "
                "path claims",
            )
        result = run_activation_phase(
            conn,
            item_id=item_id,
            actor_id=int(actor_id),
            session_id=request.actor.session_id,
            resolved_heads=body.resolved_heads,
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


def handle_survey_ensure(request: FunctionCallRequest) -> HandlerOutcome:
    """Register or widen a selected-Dash path claim from its live survey.

    Server side of the transport-aware Dash worktree preparation: wraps
    :func:`yoke_core.domain.dash_path_claim_posture.ensure_survey_path_claim`
    unchanged so the register-vs-widen decision (which the ``register``
    function alone cannot express) stays in one place. The caller
    verifies the item work-claim holder via ``claims.work.holder_get``
    first; here the claim is attributed to the calling session, which
    the dispatcher's item-claim gate has already confirmed is the
    holder. Non-Dash items and Dash items without the path_claims
    posture no-op (``claim_id=None``).
    """
    try:
        body = SurveyEnsureRequest.model_validate(request.payload)
        item_id = _resolved_item_id(request, body.item_id)
    except Exception as exc:
        return _err("payload_invalid", f"survey_ensure payload invalid: {exc}")

    from yoke_core.domain.dash_path_claim_posture import (
        ensure_survey_path_claim,
    )
    from yoke_core.domain.path_claims import PathClaimError
    from yoke_core.domain.path_claims_register import (
        PathClaimRegistrationError,
    )
    from yoke_core.domain.path_claims_resolve import PathResolveError

    with _connect_rw() as conn:
        try:
            claim_id = ensure_survey_path_claim(
                conn,
                item_id=item_id,
                session_id=request.actor.session_id or "",
                touch_paths=list(body.touch_paths),
                integration_target=str(body.integration_target),
            )
        except (
            PathClaimError,
            PathClaimRegistrationError,
            PathResolveError,
            ValueError,
        ) as exc:
            return _err("survey_ensure_failed", str(exc))

    return HandlerOutcome(
        result_payload={"claim_id": claim_id},
        primary_success=True,
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
    "SurveyEnsureRequest",
    "SurveyEnsureResponse",
    "CoordinationDecisionBuildRequest",
    "CoordinationDecisionBuildResponse",
    "handle_required_gate",
    "handle_activation_run",
    "handle_survey_ensure",
    "handle_coordination_decision_build",
]
