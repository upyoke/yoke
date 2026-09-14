"""Register deployment-flow read and configuration functions."""

from __future__ import annotations

from yoke_core.domain.handlers import (
    deployment_common as _models,
    deployment_flow_configuration as _configuration,
    deployment_flows as _flows,
    deployment_inspection as _inspection,
)


def _register_readers(registry) -> None:
    registry.register(
        "deployment_flows.list",
        _inspection.handle_deployment_flow_list,
        _inspection.DeploymentFlowListRequest,
        _inspection.DeploymentFlowListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_inspection",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )
    for function_id, handler, request_model, response_model in (
        (
            "deployment_flows.get",
            _flows.handle_deployment_flow_get,
            _models.DeploymentFlowGetRequest,
            _models.DeploymentFlowGetResponse,
        ),
        (
            "deployment_flows.stages",
            _flows.handle_deployment_flow_stages,
            _models.DeploymentFlowStagesRequest,
            _models.DeploymentFlowStagesResponse,
        ),
    ):
        registry.register(
            function_id,
            handler,
            request_model,
            response_model,
            stability="stable",
            owner_module="yoke_core.domain.handlers.deployment_flows",
            target_kinds=["global"],
            side_effects=[],
            emitted_event_names=["YokeFunctionCalled"],
            guardrails=[],
            adapter_status="live",
            claim_required_kind=None,
        )
    registry.register(
        "deployment_flows.validate",
        _configuration.handle_deployment_flow_validate,
        _configuration.DeploymentFlowValidateRequest,
        _configuration.DeploymentFlowValidateResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_flow_configuration",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["registered_stage_targets", "runtime_schema_readback"],
        adapter_status="live",
        claim_required_kind=None,
    )


def _register_writers(registry) -> None:
    registry.register(
        "deployment_flows.create",
        _flows.handle_deployment_flow_create,
        _models.DeploymentFlowCreateRequest,
        _models.DeploymentFlowCreateResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_flows",
        target_kinds=["global"],
        side_effects=["deployment_flows_create"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["project_scoped", "flow_id_unique", "display_name_unique"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "deployment_flows.update_stages",
        _flows.handle_deployment_flow_update_stages,
        _models.DeploymentFlowUpdateStagesRequest,
        _models.DeploymentFlowUpdateStagesResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_flows",
        target_kinds=["global"],
        side_effects=["deployment_flows_stages_update"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["definition_immutable_after_run", "runtime_schema_supported"],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "deployment_flows.describe",
        _flows.handle_deployment_flow_describe,
        _models.DeploymentFlowDescribeRequest,
        _models.DeploymentFlowDescribeResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_flows",
        target_kinds=["global"],
        side_effects=["deployment_flows_description_update"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["definition_immutable_after_run"],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "deployment_flows.set_status",
        _flows.handle_deployment_flow_set_status,
        _models.DeploymentFlowSetStatusRequest,
        _models.DeploymentFlowSetStatusResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_flows",
        target_kinds=["global"],
        side_effects=["deployment_flows_status_update"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["history_preserved", "runtime_schema_supported"],
        adapter_status="live",
        claim_required_kind=None,
    )
    for function_id, handler, request_model, response_model, effect in (
        (
            "deployment_flows.update",
            _configuration.handle_deployment_flow_update,
            _configuration.DeploymentFlowUpdateRequest,
            _configuration.DeploymentFlowUpdateResponse,
            "deployment_flows_update",
        ),
        (
            "deployment_flows.reorder",
            _configuration.handle_deployment_flow_reorder,
            _configuration.DeploymentFlowReorderRequest,
            _configuration.DeploymentFlowReorderResponse,
            "deployment_flows_stages_update",
        ),
        (
            "deployment_flows.version",
            _configuration.handle_deployment_flow_version,
            _configuration.DeploymentFlowVersionRequest,
            _configuration.DeploymentFlowVersionResponse,
            "deployment_flows_create",
        ),
    ):
        registry.register(
            function_id,
            handler,
            request_model,
            response_model,
            stability="stable",
            owner_module="yoke_core.domain.handlers.deployment_flow_configuration",
            target_kinds=["global"],
            side_effects=[effect],
            emitted_event_names=["YokeFunctionCalled"],
            guardrails=["definition_immutable_after_run", "runtime_schema_supported"],
            adapter_status="live",
            claim_required_kind=None,
        )


def register(registry) -> None:
    _register_readers(registry)
    _register_writers(registry)


__all__ = ["register"]
