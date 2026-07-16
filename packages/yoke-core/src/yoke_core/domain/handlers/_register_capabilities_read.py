"""Handler registration for the project-capability roster read."""

from __future__ import annotations

from yoke_core.domain.handlers import capabilities_list as _cl


def register(registry) -> None:
    registry.register(
        "projects.capabilities.list", _cl.handle_capabilities_list,
        _cl.CapabilitiesListRequest, _cl.CapabilitiesListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.capabilities_list",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )


__all__ = ["register"]
