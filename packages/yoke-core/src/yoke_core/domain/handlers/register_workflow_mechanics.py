"""Function registry entries for bounded workflow mechanics editing."""

from __future__ import annotations

from yoke_core.domain.handlers import workflow_mechanics as _mechanics


def _register_read(registry) -> None:
    registry.register(
        "workflows.mechanics.get",
        _mechanics.handle_mechanics_get,
        _mechanics.MechanicsGetRequest,
        _mechanics.MechanicsGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.workflow_mechanics",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["authoritative_project_defaults"],
        adapter_status="live",
        claim_required_kind=None,
    )


def _register_write(
    registry, function_id, handler, request_model, side_effect, guardrails,
) -> None:
    registry.register(
        function_id,
        handler,
        request_model,
        _mechanics.MutationResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.workflow_mechanics",
        target_kinds=["global"],
        side_effects=[side_effect],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=guardrails,
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )


def register(registry) -> None:
    _register_read(registry)
    _register_write(
        registry,
        "workflows.testing_default.set",
        _mechanics.handle_testing_default_set,
        _mechanics.TestingDefaultSetRequest,
        "qa_plan_project_defaults_update",
        ["project_owned", "workflow_qa_checkpoints_only"],
    )
    _register_write(
        registry,
        "workflows.delivery_default.set",
        _mechanics.handle_delivery_default_set,
        _mechanics.DeliveryDefaultSetRequest,
        "workflow_delivery_default_update",
        ["project_owned", "project_flow_only"],
    )
    _register_write(
        registry,
        "workflows.approval_defaults.publish",
        _mechanics.handle_approval_defaults_publish,
        _mechanics.ApprovalDefaultsPublishRequest,
        "workflows_version_publish",
        [
            "bounded_policy_defaults_only",
            "immutable_version_publish",
            "expected_current_version",
            "new_items_only",
        ],
    )


__all__ = ["register"]
