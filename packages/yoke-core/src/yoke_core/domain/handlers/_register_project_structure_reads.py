"""Handler registrations for project_structure read helpers."""

from __future__ import annotations

from yoke_core.domain.handlers import project_structure as _ps


def register(registry) -> None:
    """Register read-only Project Structure helper handlers."""
    registry.register(
        "project_structure.deploy_defaults.get",
        _ps.handle_project_structure_deploy_defaults_get,
        _ps.ProjectStructureDeployDefaultsGetRequest,
        _ps.ProjectStructureDeployDefaultsGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.project_structure",
        target_kinds=["project_structure"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "project_structure.get",
        _ps.handle_project_structure_get,
        _ps.ProjectStructureGetRequest,
        _ps.ProjectStructureGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.project_structure",
        target_kinds=["project_structure"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "project_structure.architecture_health.get",
        _ps.handle_architecture_health_get,
        _ps.ArchitectureHealthGetRequest,
        _ps.ArchitectureHealthGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.project_structure",
        target_kinds=["project_structure", "global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "project_structure.architecture_draft.get",
        _ps.handle_architecture_draft_get,
        _ps.ArchitectureDraftGetRequest,
        _ps.ArchitectureDraftGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.project_structure",
        target_kinds=["project_structure", "global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )


__all__ = ["register"]
