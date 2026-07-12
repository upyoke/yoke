"""Handler registrations for project GitHub App repository bindings."""

from __future__ import annotations

from yoke_core.domain.handlers import (
    project_github_binding as _project_github_binding,
)


def register(registry) -> None:
    registry.register(
        "projects.github_binding.bind",
        _project_github_binding.handle_project_github_binding_bind,
        _project_github_binding.ProjectGithubBindingBindRequest,
        _project_github_binding.ProjectGithubBindingStatusResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.project_github_binding",
        target_kinds=["global"],
        side_effects=[
            "github_app_installations_upsert",
            "project_github_repo_bindings_upsert",
            "project_capabilities_upsert",
            "projects_update",
        ],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "projects.github_binding.unbind",
        _project_github_binding.handle_project_github_binding_unbind,
        _project_github_binding.ProjectGithubBindingUnbindRequest,
        _project_github_binding.ProjectGithubBindingStatusResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.project_github_binding",
        target_kinds=["global"],
        side_effects=[
            "project_github_repo_bindings_delete",
            "project_capabilities_delete",
            "projects_update",
        ],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "projects.github_binding.lifecycle",
        _project_github_binding.handle_project_github_binding_lifecycle,
        _project_github_binding.ProjectGithubBindingLifecycleRequest,
        _project_github_binding.ProjectGithubBindingStatusResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.project_github_binding",
        target_kinds=["global"],
        side_effects=[
            "github_app_installations_update",
            "project_github_repo_bindings_update",
            "project_capabilities_upsert",
        ],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["service_token_required"],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "projects.github_binding.status",
        _project_github_binding.handle_project_github_binding_status,
        _project_github_binding.ProjectGithubBindingStatusRequest,
        _project_github_binding.ProjectGithubBindingStatusResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.project_github_binding",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )


__all__ = ["register"]
