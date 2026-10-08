"""Register the universe execution levels read and write."""

from __future__ import annotations

from yoke_core.domain.handlers import universe_levels as _levels


def register(registry) -> None:
    registry.register(
        _levels.GET_FUNCTION_ID,
        _levels.handle_universe_levels_get,
        _levels.UniverseLevelsGetRequest,
        _levels.UniverseLevelsResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.universe_levels",
        minimum_serving_version="next-release",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        _levels.SET_FUNCTION_ID,
        _levels.handle_universe_levels_set,
        _levels.UniverseLevelsSetRequest,
        _levels.UniverseLevelsResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.universe_levels",
        minimum_serving_version="next-release",
        target_kinds=["global"],
        side_effects=["universe_settings_upsert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["org_admin"],
        adapter_status="live",
        claim_required_kind=None,
    )


__all__ = ["register"]
