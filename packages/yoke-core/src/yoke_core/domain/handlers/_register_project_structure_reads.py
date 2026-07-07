"""Handler registrations for project_structure read helpers."""

from __future__ import annotations

from yoke_core.domain.handlers import project_structure as _ps


def register(registry) -> None:
    """Register read-only Project Structure helper handlers."""
    registry.register(
        "project_structure.command_definitions.get",
        _ps.handle_project_structure_command_definitions_get,
        _ps.ProjectStructureCommandDefinitionsGetRequest,
        _ps.ProjectStructureCommandDefinitionsGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.project_structure",
        target_kinds=["project_structure"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "project_structure.command_definitions.list",
        _ps.handle_project_structure_command_definitions_list,
        _ps.ProjectStructureCommandDefinitionsListRequest,
        _ps.ProjectStructureCommandDefinitionsListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.project_structure",
        target_kinds=["project_structure"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
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


__all__ = ["register"]
