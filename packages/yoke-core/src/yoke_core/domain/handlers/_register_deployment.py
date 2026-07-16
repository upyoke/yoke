"""Register deployment flow/run function handlers."""

from __future__ import annotations

from yoke_core.domain.handlers import (
    deployment_common as _models,
    deployment_flows as _flows,
    deployment_receipts as _receipts,
    deployment_runs as _runs,
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
    registry.register(
        "deployment_flow_receipts.get", _receipts.handle_flow_receipt_get,
        _receipts.DeploymentFlowReceiptGetRequest,
        _receipts.DeploymentFlowReceiptGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_receipts",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["digest_verified"], adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "deployment_flow_receipts.list", _receipts.handle_flow_receipt_list,
        _receipts.DeploymentFlowReceiptListRequest,
        _receipts.DeploymentFlowReceiptListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_receipts",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["digest_verified"], adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "deployment_run_receipts.get", _receipts.handle_run_receipt_get,
        _receipts.DeploymentRunReceiptGetRequest,
        _receipts.DeploymentRunReceiptGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_receipts",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["digest_verified"], adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "deployment_run_receipts.list", _receipts.handle_run_receipt_list,
        _receipts.DeploymentRunReceiptListRequest,
        _receipts.DeploymentRunReceiptListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.deployment_receipts",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["digest_verified"], adapter_status="live",
        claim_required_kind=None,
    )


__all__ = ["register"]
