"""Register the universe execution levels reads and write."""

from __future__ import annotations

from yoke_core.domain.handlers import universe_levels as _levels
from yoke_core.domain.handlers import quota_pool_order as _pools


def register(registry) -> None:
    for function_id, handler, request_model, writes in (
        (_pools.GET_FUNCTION_ID, _pools.handle_get, _pools.GetRequest, False),
        (
            _pools.SET_FUNCTION_ID,
            _pools.handle_set,
            _pools.SetRequest,
            True,
        ),
    ):
        registry.register(
            function_id,
            handler,
            request_model,
            _pools.OrderResponse,
            stability="stable",
            owner_module="yoke_core.domain.handlers.quota_pool_order",
            minimum_serving_version="next-release",
            target_kinds=["global"],
            side_effects=["universe_settings_upsert"] if writes else [],
            guardrails=["org_admin"] if writes else [],
            adapter_status="live",
            claim_required_kind=None,
            ambient_session_required=writes,
        )
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
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        _levels.CAPACITY_FUNCTION_ID,
        _levels.handle_universe_levels_capacity_get,
        _levels.UniverseLevelsGetRequest,
        _levels.UniverseLevelsCapacityResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.universe_levels",
        minimum_serving_version="next-release",
        target_kinds=["global"],
        side_effects=[],
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
        guardrails=["org_admin"],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        _levels.RESET_FUNCTION_ID,
        _levels.handle_universe_levels_reset,
        _levels.UniverseLevelsGetRequest,
        _levels.UniverseLevelsResetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.universe_levels",
        minimum_serving_version="next-release",
        target_kinds=["global"],
        side_effects=["universe_settings_delete"],
        guardrails=["org_admin"],
        adapter_status="live",
        claim_required_kind=None,
    )


__all__ = ["register"]
