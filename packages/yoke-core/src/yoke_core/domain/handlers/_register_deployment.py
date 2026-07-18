"""Register deployment flow/run function handlers."""

from __future__ import annotations

from yoke_core.domain.handlers import (
    deployment_common as _models,
    deployment_flows as _flows,
    deployment_runs as _runs,
    deployment_runs_composed as _runs_composed,
)


def register(registry) -> None:
    """Register deployment flow/run wrappers via the given registry."""
    registry.register(
        "deployment_flows.get", _flows.handle_deployment_flow_get,
        _models.DeploymentFlowGetRequest,
        _models.DeploymentFlowGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_flows",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "deployment_flows.stages", _flows.handle_deployment_flow_stages,
        _models.DeploymentFlowStagesRequest,
        _models.DeploymentFlowStagesResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_flows",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
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
        guardrails=["definition_immutable_after_run"],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "deployment_flows.reconcile_project",
        _flows.handle_deployment_flow_reconcile_project,
        _models.DeploymentFlowReconcileProjectRequest,
        _models.DeploymentFlowReconcileProjectResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_flows",
        target_kinds=["global"],
        side_effects=[
            "deployment_flows_reconcile",
            "project_structure_update",
        ],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[
            "project_scoped",
            "history_preserved",
            "referenced_definitions_immutable",
        ],
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
        guardrails=["history_preserved"],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "deployment_runs.get", _runs.handle_deployment_run_get,
        _models.DeploymentRunGetRequest,
        _models.DeploymentRunGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_runs",
        target_kinds=["workflow_run"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "deployment_runs.create", _runs.handle_deployment_run_create,
        _models.DeploymentRunCreateRequest,
        _models.DeploymentRunCreateResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_runs",
        target_kinds=["global"],
        side_effects=["deployment_runs_insert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["zero_member_environment_run"],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "deployment_runs.start_for_item",
        _runs_composed.handle_deployment_run_start_for_item,
        _models.DeploymentRunStartForItemRequest,
        _models.DeploymentRunStartForItemResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_runs",
        target_kinds=["item"],
        side_effects=[
            "deployment_runs_insert",
            "deployment_run_items_insert",
        ],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["item_bound_composition_validation"],
        adapter_status="live",
        claim_required_kind="item",
    )
    registry.register(
        "deployment_runs.list", _runs.handle_deployment_run_list,
        _models.DeploymentRunListRequest,
        _models.DeploymentRunListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_runs",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "deployment_runs.approve", _runs.handle_deployment_run_approve,
        _models.DeploymentRunApproveRequest,
        _models.DeploymentRunApproveResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_runs",
        target_kinds=["workflow_run"],
        side_effects=["deployment_runs_update", "items_deploy_stage_update"],
        emitted_event_names=["DeploymentApprovalGranted", "YokeFunctionCalled"],
        guardrails=["executing_run", "current_stage_human_approval"],
        adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "deployment_runs.update", _runs.handle_deployment_run_update,
        _models.DeploymentRunUpdateRequest,
        _models.DeploymentRunUpdateResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_runs",
        target_kinds=["workflow_run"],
        side_effects=["deployment_runs_update"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "deployment_runs.resolve_target_env",
        _runs.handle_deployment_run_resolve_target_env,
        _models.DeploymentRunResolveTargetEnvRequest,
        _models.DeploymentRunResolveTargetEnvResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_runs",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )


__all__ = ["register"]
