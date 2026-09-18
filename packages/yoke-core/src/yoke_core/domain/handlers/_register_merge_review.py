"""Registration for the merge boundary's candidate-review gate.

Kept out of the Inbox leaf because every registration there is
``adapter_status='internal'`` -- a decision surface the product drives and no
agent CLI reaches. This one is the opposite: the merge boundary and a
reviewer both call it by name, so it ships a CLI adapter.
"""

from __future__ import annotations

from yoke_core.domain.handlers import merge_candidate_review as _candidate


def register(registry) -> None:
    registry.register(
        _candidate.FUNCTION_ID,
        _candidate.handle_candidate_evaluate,
        _candidate.CandidateReviewEvaluateRequest,
        _candidate.CandidateReviewEvaluateResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.merge_candidate_review",
        target_kinds=["item"],
        side_effects=["decision_requests_insert", "decision_requests_withdraw"],
        emitted_event_names=[
            "YokeFunctionCalled",
            "DecisionRequestCreated",
            "DecisionRequestWithdrawn",
        ],
        guardrails=["typed_subject", "authority_union", "closed_kind"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )


__all__ = ["register"]
