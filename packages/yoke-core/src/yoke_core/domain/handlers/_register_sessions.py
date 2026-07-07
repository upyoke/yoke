"""Handler registrations for sessions.* and charge.schedule wrappers."""

from __future__ import annotations

from yoke_core.domain.handlers import sessions_orchestration as _so


def register(registry) -> None:
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
        "charge.schedule", _so.handle_charge_schedule,
        _so.ChargeScheduleRequest, _so.ChargeScheduleResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.sessions_orchestration",
        target_kinds=["global"],
        side_effects=["events_insert"],
        emitted_event_names=["FrontierStepSelected", "YokeFunctionCalled"],
        guardrails=["project_scope_resolved"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )


__all__ = ["register"]
