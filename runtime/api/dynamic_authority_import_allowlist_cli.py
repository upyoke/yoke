"""Additional dynamic engine-import allowlist entries for CLI adapters.

Kept beside the main roster so that roster can stay under the authored-file
line limit while new CLI adapter call sites continue to register.
"""

from __future__ import annotations

CLI_ADAPTER_DYNAMIC_AUTHORITY_IMPORTS = {
    (
        "packages/yoke-cli/src/yoke_cli/commands/merge_item_local_runtime.py",
        "yoke_core.domain.project_github_auth",
    ): (
        "machine_local_credential_custody",
        "bind refresh-only GitHub user authority inside the merge child",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/merge_item_local_runtime.py",
        "yoke_core.domain.standalone_item_merge_cli",
    ): (
        "client_local_execution",
        "execute repository merge mechanics in the isolated local child",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/transport/local_github_dispatch.py",
        "yoke_core.domain.project_github_auth",
    ): (
        "local_universe_dispatch",
        "project-scoped GitHub App token dispatch for a local universe",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/transport/local_github_dispatch.py",
        "yoke_core.domain.github_actions_local_authority",
    ): (
        "local_universe_dispatch",
        "explicit attended GitHub Actions bootstrap dispatcher",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/hooks.py",
        "runtime.harness.hook_runner.local_universe_lifecycle",
    ): (
        "local_universe_dispatch",
        "drive the in-process session lifecycle for a bound local universe",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/hooks.py",
        "yoke_core.domain.session_orientation",
    ): (
        "client_local_diagnostics",
        "compose session orientation from this machine's own git and files",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/dash.py",
        "yoke_core.domain.verification_tree_binding",
    ): ("client_local_diagnostics", "name the verification tree from git"),
    (
        "packages/yoke-cli/src/yoke_cli/commands/migration_rehearse.py",
        "yoke_core.domain.migration_apply",
    ): ("source_dev_admin", "CLI adapter delegates migration rehearsal"),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/doctor_https_compose.py",
        "yoke_core.engines.doctor_https_compose",
    ): (
        "client_local_diagnostics",
        "https doctor re-runs source-checkout HCs against this machine's tree",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/doctor_https_compose.py",
        "yoke_core.engines.doctor_https_only",
    ): (
        "client_local_diagnostics",
        "https doctor honors caller-checkout project-local --only slugs",
    ),
}

__all__ = ["CLI_ADAPTER_DYNAMIC_AUTHORITY_IMPORTS"]
