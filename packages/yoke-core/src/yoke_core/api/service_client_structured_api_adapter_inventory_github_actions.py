"""GitHub Actions entries for the structured API adapter inventory."""

from __future__ import annotations

from typing import Tuple

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry as _read_entry,
)


GITHUB_ACTIONS_ADAPTERS: Tuple[AdapterEntry, ...] = (
    _read_entry(
        function_id="github_actions.check_ci",
        cli_invocation=(
            "yoke github-actions check-ci <owner/repo> "
            "<workflow-file> --branch main --project <project>"
        ),
        notes=(
            "bearer-token main-branch CI advisory via gh_rest_transport; "
            "single-shot handler. --wait/--timeout poll CLIENT-side in "
            "the adapter, one dispatch per poll."
        ),
    ),
    _read_entry(
        function_id="github_actions.wait_run",
        cli_invocation=(
            "yoke github-actions wait-run <owner/repo> <run-id> "
            "--timeout SEC --project <project>"
        ),
        notes=(
            "bearer-token workflow-run polling wrapper. The registered "
            "server read is single-shot; wait/timeout stays client-side."
        ),
    ),
    AdapterEntry(
        function_id="github_actions.runners.status",
        cli_invocation=(
            "YOKE_ENV=prod-db-admin yoke github-actions runners status "
            "<owner/repo> --required-label self-hosted --required-label "
            "Linux --required-label ARM64 --required-label "
            "yoke-github-actions --project <project>"
        ),
        notes=(
            "Read-only repo self-hosted-runner status plus capability "
            "routing_enabled and Pulumi-owned YOKE_LINUX_RUNS_ON drift "
            "probe via gh_rest_transport; source-dev/admin CI-capacity "
            "setup surface."
        ),
    ),
    AdapterEntry(
        function_id="github_actions.secret.set",
        cli_invocation=(
            "yoke github-actions secret set <owner/repo> <secret-name> "
            "VALUE --project <project>"
        ),
        notes=(
            "Sealed-box repo-secret create-or-update via "
            "github_secrets_rest; direct VALUE is the default."
        ),
    ),
    AdapterEntry(
        function_id="github_actions.variable.get",
        cli_invocation=(
            "yoke github-actions variable get <owner/repo> <variable-name> "
            "--project <project>"
        ),
        notes=(
            "Read-only repo-variable probe via github_variables_rest; "
            "exists=false when absent."
        ),
    ),
    AdapterEntry(
        function_id="github_actions.variable.set",
        cli_invocation=(
            "yoke github-actions variable set <owner/repo> "
            "<variable-name> --value VALUE --project <project>"
        ),
        notes="bearer-token repo-variable upsert via github_variables_rest.",
    ),
)


__all__ = ["GITHUB_ACTIONS_ADAPTERS"]
