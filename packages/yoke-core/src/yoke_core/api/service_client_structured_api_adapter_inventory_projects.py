"""Project-family CLI adapter inventory entries."""

from __future__ import annotations

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry as _read_entry,
)


PROJECT_ADAPTERS = [
    AdapterEntry(
        function_id="files.upload",
        cli_invocation=(
            "yoke files upload LOCAL_FILE [--path DEST/PATH.ext] [--project P] [--session-id S] [--json]"
        ),
        notes="stores a shared file and prints its stable read URL",
    ),
    AdapterEntry(
        function_id="projects.retire",
        cli_invocation=(
            "yoke projects retire --project P --reason TEXT [--json] [--session-id S]"
        ),
        notes="hides an obligation-free project while preserving history",
    ),
    AdapterEntry(
        function_id="projects.unretire",
        cli_invocation=("yoke projects unretire --project P [--json] [--session-id S]"),
        notes="restores a retired project to active inventories",
    ),
    AdapterEntry(
        function_id="projects.github_binding.bind",
        cli_invocation=(
            "yoke projects github-binding bind --project P --installation-id ID --repository-id ID --github-repo OWNER/REPO [--session-id S] [--json]"
        ),
        notes=(
            "verifies and binds a project to a GitHub App installation "
            "repository using the local App user authorization"
        ),
    ),
    AdapterEntry(
        function_id="projects.github_binding.unbind",
        cli_invocation=(
            "yoke projects github-binding unbind --project P [--session-id S] [--json]"
        ),
        notes="removes the repo binding and marks the project disabled",
    ),
    _read_entry(
        function_id="projects.github_binding.status",
        cli_invocation=(
            "yoke projects github-binding status --project P [--field github_repo] [--full] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="projects.github_binding.check",
        cli_invocation=(
            "yoke projects github-binding check --project P [--session-id S] [--json]"
        ),
        notes=(
            "re-verifies the stored binding with GitHub and refreshes its "
            "last-checked time; local and self-hosted universes have no "
            "webhooks, so this is how their GitHub facts stay current"
        ),
    ),
    AdapterEntry(
        function_id="projects.github_sync_mode.repair",
        cli_invocation=(
            "yoke projects github-sync-mode repair [--project NAME] "
            "[--apply] [--json] [--session-id S]"
        ),
        notes=(
            "dry-runs by default; --apply normalizes effectively-enabled "
            "projects that lack an active verified App binding to disabled"
        ),
    ),
    _read_entry(
        function_id="projects.capabilities.list",
        cli_invocation=(
            "yoke projects capabilities list [--project P] [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="projects.infrastructure.list",
        cli_invocation=(
            "yoke projects infrastructure list --project NAME [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="projects.environment.list",
        cli_invocation=(
            "yoke projects environment list --project P [--json] [--session-id S]"
        ),
    ),
    _read_entry(
        function_id="project_structure.get",
        cli_invocation=(
            "yoke project-structure get --project NAME [--family F] [--full] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="projects.site.create",
        cli_invocation=(
            "yoke projects site create --project P --site NAME [--settings-json JSON] [--session-id S] [--json]"
        ),
        notes=("idempotent site registration by the project's readable name"),
    ),
    AdapterEntry(
        function_id="projects.environment.create",
        cli_invocation=(
            "yoke projects environment create --project P --site NAME --environment NAME [--url URL] [--settings-json JSON] [--session-id S] [--json]"
        ),
        notes=(
            "idempotent environment registration by readable name under a "
            "project-owned site; names are unique within the project; "
            "--url writes environments.url, the origin identity probes"
        ),
    ),
    AdapterEntry(
        function_id="projects.environment.update",
        cli_invocation=(
            "yoke projects environment update --project P --environment NAME [--name NAME] [--url URL] [--session-id S] [--json]"
        ),
        notes=(
            "updates an existing environment selected by its current readable "
            "name; --name must remain unique within the project; --url "
            "writes environments.url without renaming"
        ),
    ),
]


__all__ = ["PROJECT_ADAPTERS"]
