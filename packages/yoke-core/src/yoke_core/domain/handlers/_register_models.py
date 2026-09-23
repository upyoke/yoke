"""Register sourced model catalog read and publication handlers."""

from __future__ import annotations

from yoke_core.domain.handlers import model_reference as _models
from yoke_core.domain.handlers import model_reference_publication as _publication


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
    registry.register(
        _publication.DIFF_FUNCTION_ID,
        _publication.handle_models_diff,
        _publication.ModelsDiffRequest,
        _publication.ModelsDiffResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.model_reference_publication",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
        minimum_serving_version="next-release",
    )
    registry.register(
        _publication.REVISIONS_FUNCTION_ID,
        _publication.handle_models_revisions,
        _publication.ModelsRevisionsRequest,
        _publication.ModelsRevisionsResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.model_reference_publication",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
        minimum_serving_version="next-release",
    )
    for function_id, handler, request_type in (
        (
            _publication.PUBLISH_FUNCTION_ID,
            _publication.handle_models_publish,
            _publication.ModelsPublishRequest,
        ),
        (
            _publication.RESTORE_FUNCTION_ID,
            _publication.handle_models_restore,
            _publication.ModelsRestoreRequest,
        ),
    ):
        registry.register(
            function_id,
            handler,
            request_type,
            _publication.ModelsPublishResponse,
            stability="stable",
            owner_module="yoke_core.domain.handlers.model_reference_publication",
            target_kinds=["global"],
            side_effects=["model_reference_revisions_insert"],
            emitted_event_names=["YokeFunctionCalled"],
            guardrails=["org_admin"],
            adapter_status="live",
            claim_required_kind=None,
            minimum_serving_version="next-release",
        )


__all__ = ["register"]
