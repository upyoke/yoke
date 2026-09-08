"""Function-registry entries for hosted path-boundary proof flow."""

from __future__ import annotations

from yoke_core.domain.handlers import claims_path_boundary as _boundary


def register(registry) -> None:
    registry.register(
        "claims.path.boundary_context",
        _boundary.handle_boundary_context,
        _boundary.BoundaryContextRequest,
        _boundary.BoundaryContextResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_path_boundary",
        target_kinds=["item"],
        side_effects=[],
        emitted_event_names=[],
        guardrails=["actor_holds_item_claim"],
        adapter_status="internal",
        claim_required_kind="item",
    )
    registry.register(
        "claims.path.boundary_prove",
        _boundary.handle_boundary_prove,
        _boundary.BoundaryProveRequest,
        _boundary.BoundaryProveResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.claims_path_boundary",
        target_kinds=["item"],
        side_effects=["item_gate_satisfactions_upsert"],
        emitted_event_names=["GateSatisfierRungStamped"],
        guardrails=["actor_holds_item_claim", "current_boundary_facts"],
        adapter_status="live",
        claim_required_kind="item",
    )


__all__ = ["register"]
