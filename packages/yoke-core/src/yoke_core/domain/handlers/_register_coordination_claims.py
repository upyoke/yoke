"""Register the shared-operation coordination-claim function family."""

from __future__ import annotations

from yoke_core.domain.handlers import (
    claims_coordination_claim as _claims,
    claims_coordination_claim_operator as _operator,
)


def register(registry) -> None:
    registry.register(
        "claims.coordination_claim.acquire",
        _claims.handle_acquire,
        _claims.AcquireRequest,
        _claims.AcquireResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_coordination_claim",
        target_kinds=["global"],
        side_effects=["work_claims_insert"],
        emitted_event_names=["LeaseAcquired"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "claims.coordination_claim.heartbeat",
        _claims.handle_heartbeat,
        _claims.HeartbeatRequest,
        _claims.HeartbeatResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_coordination_claim",
        target_kinds=["global"],
        side_effects=["work_claims_update_heartbeat"],
        emitted_event_names=["LeaseHeartbeated"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "claims.coordination_claim.release",
        _claims.handle_release,
        _claims.ReleaseRequest,
        _claims.ReleaseResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_coordination_claim",
        target_kinds=["global"],
        side_effects=["work_claims_update_released_at"],
        emitted_event_names=["LeaseReleased"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "claims.coordination_claim.operator_release",
        _operator.handle_operator_release,
        _operator.OperatorReleaseRequest,
        _operator.OperatorReleaseResponse,
        stability="stable",
        owner_module=("yoke_core.domain.handlers.claims_coordination_claim_operator"),
        target_kinds=["global"],
        side_effects=["work_claims_update_released_at"],
        emitted_event_names=["OperatorLeaseRelease", "LeaseReleased"],
        guardrails=[
            "authenticated_human_actor_required",
            "harness_session_refused",
            "human_only_hook_guard",
            "exact_claim_holder_precondition",
            "operator_reason_required",
        ],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "claims.coordination_claim.list",
        _claims.handle_list,
        _claims.ListRequest,
        _claims.ListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_coordination_claim",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=[],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )


__all__ = ["register"]
