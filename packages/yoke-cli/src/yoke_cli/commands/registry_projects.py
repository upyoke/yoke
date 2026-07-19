"""Project command entries for the aggregate ``yoke`` registry."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands import flag_adapters as _adapters


AdapterFn = Callable[[List[str]], int]


PROJECTS_SUBCOMMAND_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("projects", "get"): ("projects.get", _adapters.projects_get),
    ("projects", "list"): ("projects.list", _adapters.projects_list),
    ("projects", "resolve-by-github-repo"): (
        "projects.resolve_by_github_repo",
        _adapters.projects_resolve_by_github_repo,
    ),
    ("projects", "create"): ("projects.create", _adapters.projects_create),
    ("projects", "update"): ("projects.update", _adapters.projects_update),
    ("projects", "capability", "has"): (
        "projects.capability.has",
        _adapters.projects_capability_has,
    ),
    ("projects", "capabilities", "list"): (
        "projects.capabilities.list",
        _adapters.projects_capabilities_list,
    ),
    ("projects", "capability-settings", "get"): (
        "projects.capability_settings.get",
        _adapters.projects_capability_settings_get,
    ),
    ("projects", "capability-settings", "set"): (
        "projects.capability_settings.set",
        _adapters.projects_capability_settings_set,
    ),
    ("projects", "capability-settings", "merge"): (
        "projects.capability_settings.merge",
        _adapters.projects_capability_settings_merge,
    ),
    ("projects", "capability-settings", "remove"): (
        "projects.capability_settings.remove",
        _adapters.projects_capability_settings_remove,
    ),
    ("projects", "environment-settings", "get"): (
        "projects.environment_settings.get",
        _adapters.projects_environment_settings_get,
    ),
    ("projects", "environment-settings", "merge"): (
        "projects.environment_settings.merge",
        _adapters.projects_environment_settings_merge,
    ),
    ("projects", "infrastructure", "list"): (
        "projects.infrastructure.list",
        _adapters.projects_infrastructure_list,
    ),
    ("projects", "pulumi-state", "migrate"): (
        "projects.pulumi_state.migrate",
        _adapters.projects_pulumi_state_migrate,
    ),
    ("projects", "pulumi-state", "checkpoint-import"): (
        "projects.pulumi_state.checkpoint_import",
        _adapters.projects_pulumi_state_checkpoint_import,
    ),
    ("projects", "pulumi-stack-config", "get"): (
        "projects.pulumi_stack_config.get",
        _adapters.projects_pulumi_stack_config_get,
    ),
    ("projects", "capability-secret", "set"): (
        "projects.capability_secret.set",
        _adapters.projects_capability_secret_set,
    ),
    ("projects", "checkout-context"): (
        "projects.checkout_context.run",
        _adapters.projects_checkout_context,
    ),
    ("projects", "github-binding", "bind"): (
        "projects.github_binding.bind",
        _adapters.projects_github_binding_bind,
    ),
    ("projects", "github-binding", "unbind"): (
        "projects.github_binding.unbind",
        _adapters.projects_github_binding_unbind,
    ),
    ("projects", "github-binding", "status"): (
        "projects.github_binding.status",
        _adapters.projects_github_binding_status,
    ),
    ("projects", "github-sync-mode", "repair"): (
        "projects.github_sync_mode.repair",
        _adapters.projects_github_sync_mode_repair,
    ),
    ("project", "register"): (
        "project.register.run",
        _adapters.project_register,
    ),
    ("project", "install"): (
        "project.install.run",
        _adapters.project_install,
    ),
    ("project", "refresh"): (
        "project.refresh.run",
        _adapters.project_refresh,
    ),
    ("project", "uninstall"): (
        "project.uninstall.run",
        _adapters.project_uninstall,
    ),
    ("project", "snapshot", "sync"): (
        "project.snapshot.sync",
        _adapters.project_snapshot_sync,
    ),
}


__all__ = ["PROJECTS_SUBCOMMAND_REGISTRY"]
