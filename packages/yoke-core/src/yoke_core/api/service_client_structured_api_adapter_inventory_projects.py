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
            "yoke projects site create --project P --site-slug SLUG "
            "[--settings-json JSON]"
        ),
        notes=(
            "idempotent site registration: an existing slug owned by the "
            "same project reports already_present untouched; a slug owned "
            "by another project refuses"
        ),
    ),
    AdapterEntry(
        function_id="projects.environment.create",
        cli_invocation=(
            "yoke projects environment create --project P --site-slug SLUG "
            "--environment-id ID [--name prod|stage] [--settings-json JSON]"
        ),
        notes=(
            "idempotent environment registration under a project-owned "
            "site (resolves ownership through the site row); an existing "
            "id under the same site reports already_present untouched; "
            "optional --name sets the closed delivery name at insert"
        ),
    ),
    AdapterEntry(
        function_id="projects.environment.update",
        cli_invocation=(
            "yoke projects environment update --project P "
            "--environment-id ID --name prod|stage"
        ),
        notes=(
            "renames an existing environment in place; id and site stay "
            "stable and the name must be prod or stage"
        ),
    ),
]


__all__ = ["PROJECT_ADAPTERS"]
