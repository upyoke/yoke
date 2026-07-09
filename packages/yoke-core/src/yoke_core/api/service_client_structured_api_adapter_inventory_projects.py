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
            "--installation-id ID --account-id ID --account-login LOGIN "
            "--account-type TYPE --github-repo OWNER/REPO"
        ),
        notes="binds a project to a GitHub App installation repository",
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
]


__all__ = ["PROJECT_ADAPTERS"]
