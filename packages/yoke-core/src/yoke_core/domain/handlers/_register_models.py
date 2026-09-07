"""Register the sourced model-reference read/validate handlers."""

from __future__ import annotations

from yoke_core.domain.handlers import model_reference as _models


def register(registry) -> None:
    registry.register(
        _models.LOOKUP_FUNCTION_ID,
        _models.handle_models_lookup,
        _models.ModelsLookupRequest,
        _models.ModelsLookupResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.model_reference",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        _models.GET_FUNCTION_ID,
        _models.handle_models_get,
        _models.ModelsGetRequest,
        _models.ModelsGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.model_reference",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        _models.VALIDATE_FUNCTION_ID,
        _models.handle_models_validate,
        _models.ModelsValidateRequest,
        _models.ModelsValidateResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.model_reference",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )


__all__ = ["register"]
