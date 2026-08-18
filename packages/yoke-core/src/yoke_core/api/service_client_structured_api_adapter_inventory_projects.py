"""Project-family CLI adapter inventory entries."""

from __future__ import annotations

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry as _read_entry,
)


PROJECT_ADAPTERS = [
    AdapterEntry(
        function_id="projects.github_binding.bind",
        cli_invocation=(
            "yoke projects github-binding bind --project NAME "
            "--installation-id ID --repository-id ID "
            "--github-repo OWNER/REPO"
        ),
        notes=(
            "verifies and binds a project to a GitHub App installation "
            "repository using the local App user authorization"
        ),
    ),
    AdapterEntry(
        function_id="projects.github_binding.unbind",
        cli_invocation="yoke projects github-binding unbind --project NAME",
        notes="removes the repo binding and marks the project disabled",
    ),
    _read_entry(
        function_id="projects.github_binding.status",
        cli_invocation="yoke projects github-binding status --project NAME",
    ),
    AdapterEntry(
        function_id="projects.github_sync_mode.repair",
        cli_invocation=(
            "yoke projects github-sync-mode repair [--project NAME] [--apply]"
        ),
        notes=(
            "dry-runs by default; --apply normalizes effectively-enabled "
            "projects that lack an active verified App binding to disabled"
        ),
    ),
    _read_entry(
        function_id="projects.capabilities.list",
        cli_invocation="yoke projects capabilities list [--project P]",
    ),
    _read_entry(
        function_id="projects.infrastructure.list",
        cli_invocation="yoke projects infrastructure list --project NAME",
    ),
    _read_entry(
        function_id="project_structure.get",
        cli_invocation="yoke project-structure get --project NAME [--family F]",
    ),
    AdapterEntry(
        function_id="projects.site.create",
        cli_invocation=(
            "yoke projects site create --project P --site NAME "
            "[--settings-json JSON]"
        ),
        notes=(
            "idempotent site registration by the project's readable name"
        ),
    ),
    AdapterEntry(
        function_id="projects.environment.create",
        cli_invocation=(
            "yoke projects environment create --project P --site NAME "
            "--environment NAME [--settings-json JSON]"
        ),
        notes=(
            "idempotent environment registration by readable name under a "
            "project-owned site; names are unique within the project"
        ),
    ),
    AdapterEntry(
        function_id="projects.environment.update",
        cli_invocation=(
            "yoke projects environment update --project P "
            "--environment NAME --name NEW_NAME"
        ),
        notes=(
            "renames an existing environment selected by its current readable "
            "name; the new name must remain unique within the project"
        ),
    ),
]


__all__ = ["PROJECT_ADAPTERS"]
