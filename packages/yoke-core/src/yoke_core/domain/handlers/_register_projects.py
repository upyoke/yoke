"""Handler registrations for project registry and sync-policy writes.

The create/update pair is backed by the idempotent project upsert workhorse;
the explicit sync-mode repair is control-plane scoped and dry-runs by default.
Project *read* registrations still live in ``_register_qa_reads``.
"""
from __future__ import annotations

from yoke_core.domain.handlers import projects_upsert as _projects_upsert
from yoke_core.domain.handlers import (
    projects_capability_settings as _capability_settings,
)
from yoke_core.domain.handlers import (
    projects_environment_settings as _environment_settings,
)
from yoke_core.domain.handlers import (
    projects_github_sync_mode_repair as _sync_mode_repair,
)

_PROJECT_WRITE_SURFACES = (
    ("projects.create", _projects_upsert.handle_projects_create),
    ("projects.update", _projects_upsert.handle_projects_update),
)


def register(registry) -> None:
    """Register project registry writes via the given registry module."""
    for function_id, handler in _PROJECT_WRITE_SURFACES:
        registry.register(
            function_id, handler,
            _projects_upsert.ProjectsUpsertRequest,
            _projects_upsert.ProjectsUpsertResponse,
            stability="stable",
            owner_module="yoke_core.domain.handlers.projects_upsert",
            target_kinds=["global"],
            side_effects=["projects_upsert", "project_capabilities_insert"],
            emitted_event_names=["YokeFunctionCalled"],
            guardrails=[], adapter_status="live", claim_required_kind=None,
            ambient_session_required=False,
        )
    registry.register(
        "projects.capability_settings.get",
        _capability_settings.handle_capability_settings_get,
        _capability_settings.CapabilitySettingsGetRequest,
        _capability_settings.CapabilitySettingsResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.projects_capability_settings",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["non_sensitive_settings_only"], adapter_status="live",
        claim_required_kind=None, ambient_session_required=False,
    )
    for function_id, handler, request_model in (
        (
            "projects.capability_settings.set",
            _capability_settings.handle_capability_settings_set,
            _capability_settings.CapabilitySettingsSetRequest,
        ),
        (
            "projects.capability_settings.merge",
            _capability_settings.handle_capability_settings_merge,
            _capability_settings.CapabilitySettingsMergeRequest,
        ),
    ):
        registry.register(
            function_id, handler, request_model,
            _capability_settings.CapabilitySettingsResponse,
            stability="stable",
            owner_module=(
                "yoke_core.domain.handlers.projects_capability_settings"
            ),
            target_kinds=["global"],
            side_effects=["project_capabilities_settings_write"],
            emitted_event_names=["YokeFunctionCalled"],
            guardrails=[
                "value_compare_and_swap", "typed_capability_validation",
                "github_binding_owned",
            ],
            adapter_status="live", claim_required_kind=None,
            ambient_session_required=False,
        )
    registry.register(
        "projects.environment_settings.get",
        _environment_settings.handle_environment_settings_get,
        _environment_settings.EnvironmentSettingsGetRequest,
        _environment_settings.EnvironmentSettingsResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.projects_environment_settings",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["project_environment_match"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "projects.environment_settings.merge",
        _environment_settings.handle_environment_settings_merge,
        _environment_settings.EnvironmentSettingsMergeRequest,
        _environment_settings.EnvironmentSettingsResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.projects_environment_settings",
        target_kinds=["global"],
        side_effects=["environments_settings_write"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["value_compare_and_swap", "project_environment_match"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "projects.github_sync_mode.repair",
        _sync_mode_repair.handle_projects_github_sync_mode_repair,
        _sync_mode_repair.ProjectsGithubSyncModeRepairRequest,
        _sync_mode_repair.ProjectsGithubSyncModeRepairResponse,
        stability="stable",
        owner_module=(
            "yoke_core.domain.handlers.projects_github_sync_mode_repair"
        ),
        target_kinds=["global"],
        side_effects=["projects_update"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["dry_run_default", "explicit_apply_required"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
