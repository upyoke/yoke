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
        function_id="projects.github_binding.lifecycle",
        cli_invocation="HTTPS function-call only (hosted platform webhook)",
        notes=(
            "applies a signature-verified installation or repository lifecycle "
            "event to a hosted project binding"
        ),
    ),
    AdapterEntry(
        function_id="projects.github_binding.unbind",
        cli_invocation="yoke projects github-binding unbind --project NAME",
        notes="removes the repo binding and marks the project backlog-only",
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
            "projects that lack an active verified App binding to backlog-only"
        ),
    ),
]


__all__ = ["PROJECT_ADAPTERS"]
