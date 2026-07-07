"""Handler registrations for claims.work.* + claims.path.* +
claims.coordination_lease.* + db_claim.amend handlers.
"""
from __future__ import annotations

from yoke_core.domain.handlers import (
    claims_coordination_lease as _ccl,
    claims_path as _cp,
    claims_path_activation as _cpa,
    claims_path_reads as _cpr,
    claims_work as _cw,
    claims_work_holders as _cwh,
    claims_work_release_session_scoped as _cwrs,
    db_claim as _dbc,
)


def register(registry) -> None:
    """Register task 6's handlers via the given registry module."""
    # claims.work.acquire — no claim required (chicken-and-egg)
    registry.register(
        "claims.work.acquire", _cw.handle_acquire,
        _cw.AcquireRequest, _cw.AcquireResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_work",
        target_kinds=["item", "epic_task", "global"],
        side_effects=["work_claims_insert"],
        emitted_event_names=["WorkClaimed"],
        guardrails=["no_active_claim_on_target"],
        adapter_status="live",
        claim_required_kind=None,
    )
    # claims.work.release — self_only
    registry.register(
        "claims.work.release", _cw.handle_release,
        _cw.ReleaseRequest, _cw.ReleaseResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_work",
        target_kinds=["claim", "item", "epic_task"],
        side_effects=["work_claims_update_released_at"],
        emitted_event_names=["WorkClaimReleased"],
        guardrails=["actor_owns_claim"],
        adapter_status="live",
        claim_required_kind="self_only",
    )
    # claims.work.release_session_scoped — release every claim the caller
    # still holds. claim_required_kind=None because the security boundary
    # (strict same-session WHERE filter) is enforced inside the handler,
    # not by the dispatcher's target-claim gate. Target IS the calling
    # session — no item/claim id in the envelope.
    registry.register(
        "claims.work.release_session_scoped",
        _cwrs.handle_release_session_scoped,
        _cwrs.ReleaseSessionScopedRequest,
        _cwrs.ReleaseSessionScopedResponse,
        stability="stable",
        owner_module=(
            "yoke_core.domain.handlers.claims_work_release_session_scoped"
        ),
        target_kinds=["global"],
        side_effects=["work_claims_update_released_at"],
        emitted_event_names=[
            "WorkReleased", "HarnessSessionEndReleasedClaims",
        ],
        guardrails=["same_session_filter"],
        adapter_status="live",
        claim_required_kind=None,
    )
    # claims.work.holder_get / holder_list — read-only, no claim required
    registry.register(
        "claims.work.holder_get", _cwh.handle_holder_get,
        _cwh.HolderGetRequest, _cwh.HolderGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_work_holders",
        target_kinds=["item"],
        side_effects=[],
        emitted_event_names=[],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "claims.work.holder_list", _cwh.handle_holder_list,
        _cwh.HolderListRequest, _cwh.HolderListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_work_holders",
        target_kinds=["item", "global"],
        side_effects=[],
        emitted_event_names=[],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )

    # claims.path.register / widen / amend / release — item-scoped
    registry.register(
        "claims.path.register", _cp.handle_register,
        _cp.RegisterRequest, _cp.RegisterResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_path",
        target_kinds=["item"],
        side_effects=["path_claims_insert"],
        emitted_event_names=[
            "PathClaimRegistered", "PathClaimRegistrationBlocked",
        ],
        guardrails=["actor_holds_item_claim"],
        adapter_status="live",
        claim_required_kind="item",
    )
    registry.register(
        "claims.path.widen", _cp.handle_widen,
        _cp.WidenRequest, _cp.WidenResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_path",
        target_kinds=["item"],
        side_effects=["path_claim_targets_insert", "path_claim_amendments_insert"],
        emitted_event_names=["PathClaimAmended"],
        guardrails=["actor_holds_item_claim"],
        adapter_status="live",
        claim_required_kind="item",
    )
    # claims.path.list / get — read-only projections, no claim required.
    registry.register(
        "claims.path.list", _cpr.handle_claims_path_list,
        _cpr.ClaimsPathListRequest, _cpr.ClaimsPathListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_path_reads",
        target_kinds=["item"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "claims.path.get", _cpr.handle_claims_path_get,
        _cpr.ClaimsPathGetRequest, _cpr.ClaimsPathGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_path_reads",
        target_kinds=["path_claim"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "claims.path.release", _cp.handle_release,
        _cp.ReleaseRequest, _cp.ReleaseResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_path",
        target_kinds=["item"],
        side_effects=["path_claims_update_released_at"],
        emitted_event_names=["PathClaimReleased"],
        guardrails=["actor_holds_item_claim"],
        adapter_status="live",
        claim_required_kind="item",
    )
    registry.register(
        "claims.path.amend", _cp.handle_amend,
        _cp.WidenRequest, _cp.WidenResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_path",
        target_kinds=["item"],
        side_effects=["path_claim_targets_insert", "path_claim_amendments_insert"],
        emitted_event_names=["PathClaimAmended"],
        guardrails=["actor_holds_item_claim"],
        adapter_status="live",
        claim_required_kind="item",
    )
    # claims.path.override — operator-only
    registry.register(
        "claims.path.override", _cp.handle_override,
        _cp.OverrideRequest, _cp.OverrideResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_path",
        target_kinds=["item"],
        side_effects=["path_claim_override_event"],
        emitted_event_names=["PathClaimOverride"],
        guardrails=["operator_override_required", "human_only_hook_guard"],
        adapter_status="live",
        claim_required_kind="operator_override",
    )

    # claims.path.required_gate — read-only idea/refine coverage gate
    registry.register(
        "claims.path.required_gate",
        _cpa.handle_required_gate,
        _cpa.RequiredGateRequest,
        _cpa.RequiredGateResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_path_activation",
        target_kinds=["item"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )

    # claims.path.activation_run — item-scoped
    registry.register(
        "claims.path.activation_run", _cpa.handle_activation_run,
        _cpa.ActivationRunRequest, _cpa.ActivationRunResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_path_activation",
        target_kinds=["item"],
        side_effects=["path_claims_update_state"],
        emitted_event_names=[
            "PathClaimActivated", "PathClaimActivationBlocked",
        ],
        guardrails=["actor_holds_item_claim"],
        adapter_status="live",
        claim_required_kind="item",
    )
    # claims.path.coordination_decision_build — read-only evidence packet
    registry.register(
        "claims.path.coordination_decision_build",
        _cpa.handle_coordination_decision_build,
        _cpa.CoordinationDecisionBuildRequest,
        _cpa.CoordinationDecisionBuildResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_path_activation",
        target_kinds=["item"],
        side_effects=[],
        emitted_event_names=[],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )

    # claims.coordination_lease.* — lease primitive
    registry.register(
        "claims.coordination_lease.acquire", _ccl.handle_acquire,
        _ccl.AcquireRequest, _ccl.AcquireResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_coordination_lease",
        target_kinds=["global"],
        side_effects=["coordination_leases_insert"],
        emitted_event_names=["CoordinationLeaseAcquired"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "claims.coordination_lease.heartbeat", _ccl.handle_heartbeat,
        _ccl.HeartbeatRequest, _ccl.HeartbeatResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_coordination_lease",
        target_kinds=["global"],
        side_effects=["coordination_leases_update_heartbeat"],
        emitted_event_names=["CoordinationLeaseHeartbeated"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "claims.coordination_lease.release", _ccl.handle_release,
        _ccl.ReleaseRequest, _ccl.ReleaseResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_coordination_lease",
        target_kinds=["global"],
        side_effects=["coordination_leases_update_released_at"],
        emitted_event_names=["CoordinationLeaseReleased"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "claims.coordination_lease.list", _ccl.handle_list,
        _ccl.ListRequest, _ccl.ListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_coordination_lease",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=[],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )

    # db_claim.amend — item-scoped unified amendment workflow
    registry.register(
        "db_claim.amend", _dbc.handle_amend,
        _dbc.AmendRequest, _dbc.AmendResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.db_claim",
        target_kinds=["item"],
        side_effects=[
            "items_update_db_mutation_profile",
            "items_update_db_compatibility_attestation",
        ],
        emitted_event_names=["DbClaimAmended"],
        guardrails=["actor_holds_item_claim"],
        adapter_status="live",
        claim_required_kind="item",
    )
