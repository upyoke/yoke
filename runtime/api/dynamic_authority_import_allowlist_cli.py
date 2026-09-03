"""Additional dynamic engine-import allowlist entries from the CLI package.

Kept beside the main roster so that roster can stay under the authored-file
line limit while new ``yoke_cli`` call sites continue to register. The split
is a line-budget one, not a classification: an entry belongs here or there by
where there is room, and both halves are read as one roster.
"""

from __future__ import annotations

CLI_PACKAGE_DYNAMIC_AUTHORITY_IMPORTS = {
    (
        "packages/yoke-cli/src/yoke_cli/config/universe_ui_launchd.py",
        "yoke_core.tools.launchctl_boundary",
    ): (
        "local_engine_activation",
        "the local-universe UI daemon registers its launch agent through "
        "the engine's one launchd boundary rather than calling launchctl "
        "itself",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/config/universe_ui_launchd.py",
        "yoke_core.tools.install_yoke_launcher_sweep",
    ): (
        "local_engine_activation",
        "the launch agent runs this machine's canonical yoke shim, which "
        "the engine's launcher install resolves",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/engine_upgrade_convergence.py",
        "yoke_core.domain.local_universe_convergence",
    ): (
        "local_universe_dispatch",
        "converge this machine's own universe before in-process dispatch serves it",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/engine_upgrade_convergence.py",
        "yoke_core.domain.db_backend",
    ): (
        "local_universe_dispatch",
        "read the address the engine would serve, to tell own universe from foreign",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/source_dev_run.py",
        "yoke_core.tools.source_dev_run",
    ): (
        "source_dev_admin",
        "bind arbitrary development commands to the session's claimed lane",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/merge_item_local_runtime.py",
        "yoke_core.domain.project_github_auth",
    ): (
        "machine_local_credential_custody",
        "bind machine GitHub user authority inside the merge child",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/merge_item_local_runtime.py",
        "yoke_core.domain.standalone_item_merge_cli",
    ): (
        "client_local_execution",
        "execute repository merge mechanics in the isolated local child",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/merge_item_local_runtime.py",
        "yoke_core.domain.connected_env_readiness",
    ): (
        "machine_local_connection_custody",
        "prove the selected control plane is reachable before the merge runs "
        "under it, so a dead SSH forward refuses instead of failing mid-merge",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/merge_item_local_runtime.py",
        "yoke_core.domain.standalone_item_merge_recovery",
    ): (
        "client_local_execution",
        "bind the verified item holder across the control-plane authority change",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/merge_item_local_runtime.py",
        "yoke_core.domain.close_out_control_plane_authority",
    ): (
        "client_local_execution",
        "name the operator's connection for the engine before the merge "
        "override replaces it, so close-out semantics stay with the control "
        "plane rather than with whichever engine build this child imported",
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
        "yoke_core.hooks.local_entry",
    ): (
        "local_universe_dispatch",
        "run the complete packaged hook chain for a bound local universe",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/hooks.py",
        "yoke_core.domain.session_orientation",
    ): (
        "client_local_diagnostics",
        "compose session orientation from this machine's own git and files",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/session_control_relay.py",
        "yoke_core.tools.session_relay_plist",
    ): (
        "client_local_machine_state",
        "manage the machine-local relay login item without engine authority",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/lane_tree.py",
        "yoke_core.domain.verification_tree_binding",
    ): (
        "client_local_diagnostics",
        "name the verification tree from git when no lane is recorded",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/migration_rehearse.py",
        "yoke_core.domain.migration_apply",
    ): ("source_dev_admin", "CLI adapter delegates migration rehearsal"),
    (
        "packages/yoke-cli/src/yoke_cli/commands/coordination_claim.py",
        "yoke_core.api.service_client_coordination_claims",
    ): (
        "source_dev_admin",
        "delegate audited claim recovery through the selected local authority",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/doctor_https_compose.py",
        "yoke_core.engines.doctor_https_compose",
    ): (
        "client_local_diagnostics",
        "https doctor re-runs source-checkout HCs against this machine's tree",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/doctor_https_compose.py",
        "yoke_core.engines.doctor_https_local_scope",
    ): (
        "client_local_diagnostics",
        "https doctor scopes machine checks after a relayed batch fails",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/doctor_https_compose.py",
        "yoke_core.engines.doctor_https_only",
    ): (
        "client_local_diagnostics",
        "https doctor honors caller-checkout project-local --only slugs",
    ),
    (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/db_claim.py",
        "yoke_core.domain.db_claim_prose_check",
    ): (
        "client_local_diagnostics",
        "stdin prose-vs-claim detection needs no control-plane DB",
    ),
}

__all__ = ["CLI_PACKAGE_DYNAMIC_AUTHORITY_IMPORTS"]
