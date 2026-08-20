"""Handler registrations for sessions.* and charge.schedule wrappers."""

from __future__ import annotations

from yoke_core.domain.handlers import sessions_begin as _sb
from yoke_core.domain.handlers import sessions_list as _sl
from yoke_core.domain.handlers import sessions_charge_schedule as _scs
from yoke_core.domain.handlers import sessions_orchestration as _so
from yoke_core.domain.handlers import sessions_reclaim as _sr
from yoke_core.domain.handlers import sessions_closeout as _sc
from yoke_core.domain.handlers import sessions_identity as _si


def register(registry) -> None:
    registry.register(
        "sessions.end_if_empty", _sc.handle_sessions_end_if_empty,
        _sc.SessionsEndIfEmptyRequest, _sc.SessionsEndIfEmptyResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.sessions_closeout",
        target_kinds=["global"],
        side_effects=["harness_sessions_update", "events_insert"],
        emitted_event_names=[
            "HarnessSessionEnded", "ChainEndDeferred", "YokeFunctionCalled",
        ],
        guardrails=["self_only", "claimless", "chain_budget_complete"],
        adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "sessions.list", _sl.handle_sessions_list,
        _sl.SessionsListRequest, _sl.SessionsListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.sessions_list",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "sessions.reclaim_stale", _sr.handle_sessions_reclaim_stale,
        _sr.SessionsReclaimStaleRequest, _sr.SessionsReclaimStaleResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.sessions_reclaim",
        target_kinds=["global"],
        side_effects=[
            "harness_sessions_update",
            "work_claims_update",
            "events_insert",
            "scratch_cleanup",
        ],
        emitted_event_names=[
            "HarnessSessionStaleReclaimed",
            "HarnessSessionStaleSweepCompleted",
            "ReclaimAborted",
            "WorkReclaimed",
            "YokeFunctionCalled",
        ],
        guardrails=[
            "explicit_confirmation",
            "liveness_recheck",
            "project_scope_exact",
        ],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "sessions.identity", _si.handle_identity,
        _si.IdentityRequest, _si.IdentityResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.sessions_identity",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["session_required"],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "sessions.touch", _so.handle_touch,
        _so.TouchRequest, _so.TouchResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.sessions_orchestration",
        target_kinds=["global"],
        side_effects=["harness_sessions_update", "work_claims_update"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["active_session_required"],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "sessions.checkpoint", _so.handle_checkpoint,
        _so.CheckpointRequest, _so.CheckpointResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.sessions_orchestration",
        target_kinds=["global"],
        side_effects=["harness_sessions_update", "events_insert"],
        emitted_event_names=["ChainStepCompleted", "YokeFunctionCalled"],
        guardrails=["active_session_required"],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "sessions.checkpoint_read", _so.handle_checkpoint_read,
        _so.CheckpointReadRequest, _so.CheckpointResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.sessions_orchestration",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["session_required"],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "sessions.begin", _sb.handle_begin,
        _sb.BeginRequest, _sb.BeginResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.sessions_begin",
        target_kinds=["global"],
        side_effects=[
            "harness_sessions_insert", "harness_sessions_update",
            "work_claims_update", "events_insert",
        ],
        emitted_event_names=["HarnessSessionStarted", "YokeFunctionCalled"],
        guardrails=["session_creation"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "sessions.offer", _so.handle_offer,
        _so.OfferRequest, _so.OfferResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.sessions_orchestration",
        target_kinds=["global"],
        side_effects=[
            "harness_sessions_update", "work_claims_insert",
            "work_claims_update", "events_insert",
        ],
        emitted_event_names=[
            "HarnessSessionOffered", "NextActionChosen",
            "YokeFunctionCalled",
        ],
        guardrails=["active_session_required", "offer_ownership_guard"],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "sessions.ownership_guard", _so.handle_ownership_guard,
        _so.OwnershipGuardRequest, _so.OwnershipGuardResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.sessions_orchestration",
        target_kinds=["item"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["session_required"],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "charge.schedule", _scs.handle_charge_schedule,
        _scs.ChargeScheduleRequest, _scs.ChargeScheduleResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.sessions_charge_schedule",
        target_kinds=["global"],
        side_effects=["events_insert"],
        emitted_event_names=["FrontierStepSelected", "YokeFunctionCalled"],
        guardrails=["project_scope_resolved"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )


__all__ = ["register"]
