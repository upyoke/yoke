"""Register deployment flow/run function handlers."""

from __future__ import annotations

from yoke_core.domain.handlers import (
    deployment_common as _models,
    deployment_failure_trace as _failure_trace,
    deployment_inspection as _inspection,
    deployment_run_projection as _run_projection,
    deployment_run_terminalization as _run_terminalization,
    deployment_flows as _flows,
    deployment_runs as _runs,
    deployment_runs_composed as _runs_composed,
)


def register(registry) -> None:
    """Register deployment flow/run wrappers via the given registry."""
    registry.register(
        "deployment_flows.list", _inspection.handle_deployment_flow_list,
        _inspection.DeploymentFlowListRequest,
        _inspection.DeploymentFlowListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_inspection",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
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
        "deployment_flows.describe",
        _flows.handle_deployment_flow_describe,
        _models.DeploymentFlowDescribeRequest,
        _models.DeploymentFlowDescribeResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_flows",
        target_kinds=["global"],
        side_effects=["deployment_flows_description_update"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["stages_untouched"],
        adapter_status="live",
        claim_required_kind=None,
    )
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
        # Bootstrap-reachable: `yoke onboard` defines a brand-new project's
        # first flows in a plain terminal with no harness session (the
        # public-installer / brand-new-user context), so requiring an ambient
        # session here makes cold-start onboarding fail. Session-optional like
        # the sibling project-config writes in `_register_projects`: a present
        # session still binds and audits, and https callers stay project-admin
        # scoped once a numeric actor id is bound. The operator-only
        # `set_status` / `update_stages` are not part of the bootstrap path and
        # deliberately keep the session requirement.
        ambient_session_required=False,
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
        "deployment_runs.failure_trace",
        _failure_trace.handle_deployment_failure_trace,
        _failure_trace.DeploymentFailureTraceRequest,
        _failure_trace.DeploymentFailureTraceResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_failure_trace",
        target_kinds=["deployment_run"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["downstream_project_visibility", "partial_chain_on_refusal"],
        adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "deployment_runs.find_by_item",
        _inspection.handle_deployment_runs_find_by_item,
        _inspection.DeploymentRunsFindByItemRequest,
        _inspection.DeploymentRunsFindByItemResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_inspection",
        target_kinds=["item"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "deployment_runs.stages", _inspection.handle_deployment_run_stages,
        _inspection.DeploymentRunStagesRequest,
        _inspection.DeploymentRunStagesResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_inspection",
        target_kinds=["workflow_run"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["immutable_flow_definition"],
        adapter_status="live", claim_required_kind=None,
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
        "deployment_runs.project_snapshot",
        _run_projection.handle_project_snapshot,
        _run_projection.DeploymentRunProjectSnapshotRequest,
        _run_projection.DeploymentRunProjectSnapshotResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_run_projection",
        target_kinds=["global"],
        side_effects=["deployment_runs_insert", "deployment_runs_update"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[
            "canonical_snapshot",
            "identity_collision_refusal",
            "optimistic_destination_repair",
        ],
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
        "deployment_runs.terminalize",
        _run_terminalization.handle_deployment_run_terminalize,
        _run_terminalization.DeploymentRunTerminalizeRequest,
        _run_terminalization.DeploymentRunTerminalizeResponse,
        stability="stable",
        owner_module=(
            "yoke_core.domain.handlers.deployment_run_terminalization"
        ),
        target_kinds=["workflow_run"],
        side_effects=["deployment_runs_update", "events_insert"],
        emitted_event_names=[
            "DeploymentRunTerminalized", "YokeFunctionCalled",
        ],
        guardrails=[
            "active_run",
            "allowed_terminal_disposition",
            "nonempty_reason",
            "atomic_audit_event",
        ],
        adapter_status="live",
        claim_required_kind=None,
        # The loopback dashboard has no harness session. Its proxy binds the
        # sole local operator actor and the org-admin permission gate still
        # applies, so browser and CLI calls share this authority safely.
        ambient_session_required=False,
    )
    registry.register(
        "deployment_runs.resolve_target",
        _runs.handle_deployment_run_resolve_target,
        _models.DeploymentRunResolveTargetRequest,
        _models.DeploymentRunResolveTargetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_runs",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )


__all__ = ["register"]
