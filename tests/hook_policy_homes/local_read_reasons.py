"""Written reasons for local reads a server-run hook policy can reach.

Each entry names functions (``module:qualname``) whose machine-local reads
are correct wherever the chain evaluates, and says why. A read that needs
the CLIENT machine does not belong here: move its policy to the client, or
feed it a named client fact (:mod:`yoke_contracts.hook_runner.client_facts`).

``test_local_reads.py`` fails on a reached read with no reason and on a
reason whose function no longer reads anything, so this list stays exact.
"""

from __future__ import annotations

_C = "yoke_core.domain."

AUTHORITY_DATABASE = (
    "Opens the evaluating process's own control-plane database: DSN, managed "
    "secret, cloud authority, connected-environment binding and tunnel, and "
    "the retired YOKE_DB token the DB-command guards pass along. The "
    "authority connects to its own database; no client state is involved.",
    (
        "yoke_cli.config.capability_secrets:read_machine_capability_secret",
        "yoke_contracts.machine_config.directories:create_private_directory",
        "yoke_contracts.machine_config.schema_connections:selected_env",
        _C + "cloud_db_secret_dsn:env_binding_selected",
        _C + "cloud_db_secret_dsn:resolve_dsn_from_env",
        _C + "cloud_db_secret_dsn:resolve_previous_dsn_from_env",
        _C + "connected_env_readiness_connector:_tunnel_spec",
        _C + "connected_env_readiness_connector:explicit_dsn_pinned",
        _C + "connected_env_tunnel_coordination:_lock_holder",
        _C + "connected_env_tunnel_coordination:_process_command",
        _C + "connected_env_tunnel_coordination:_read_lease",
        _C + "connected_env_tunnel_coordination:active_leases",
        _C + "connected_env_tunnel_lifecycle:_find_tunnel_pids",
        _C + "connected_env_tunnel_lifecycle:_listening_pids",
        _C + "connected_env_tunnel_lifecycle:_process_command",
        _C + "connected_env_tunnel_lifecycle:_start_tunnel",
        _C + "db_backend:_managed_secret_is_active_authority",
        _C + "db_backend:resolve_pg_dsn",
        _C + "deploy_remote:_materialize_aws_env",
        _C + "deploy_remote:aws_machine_capability_env",
        _C + "lint_db_cmd:evaluate",
        _C + "lint_db_runner:run_hook",
        _C + "lint_event_registry:evaluate",
        _C + "observe_db:normalize_observe_db_path",
        _C + "postgres_connection_reuse:track_test_connection",
        _C + "yoke_cloud_db_authority:_run_cli",
        _C + "yoke_connected_env:ConnectedEnv.repo_root",
        _C + "yoke_connected_env:_credential_path",
        _C + "yoke_connected_env:find_binding",
        _C + "yoke_connected_env:load_active",
        _C + "yoke_connected_env:resolve_postgres_dsn",
        _C + "yoke_connected_env_retired_db:retired_yoke_db_path_reason",
    ),
)

AUTHORITY_TRANSPORT = (
    "Reaches the control plane through the evaluating process's own route: "
    "the CLI dispatcher with its machine config, credentials, engine "
    "handshake, install identity and relay telemetry. These describe the "
    "process making the call; the request's session and project come from "
    "the hook payload.",
    (
        "yoke_cli.commands._helpers:client_project_context",
        "yoke_cli.config.checkout_context:_git_toplevel",
        "yoke_cli.config.checkout_context:_strip_worktree_path",
        "yoke_cli.config.checkout_context:resolve_repo_root_from_cwd",
        "yoke_cli.config.machine_config:load_config",
        "yoke_cli.transport.dispatcher:_resolve_session_id",
        "yoke_cli.transport.dispatcher:build_actor",
        "yoke_cli.transport.https_credentials:resolve_token",
        "yoke_cli.transport.relay_telemetry:drain",
        "yoke_cli.transport.source_build_skew:_git",
        "yoke_contracts.install_binding:distribution_version_for_module",
        "yoke_contracts.install_binding:is_yoke_source_checkout",
        "yoke_contracts.machine_config.paths:_ambient_config_path",
        "yoke_contracts.machine_config.paths:config_path",
        "yoke_contracts.machine_config.paths:yoke_home",
        "yoke_contracts.machine_config.runtime:load_config",
        "yoke_contracts.project_contract.label_policy:read_labels_file",
    ),
)

AUTHORITY_RELEASE_MACHINERY = (
    "Reached only through the static over-approximation of control-plane "
    "gate code (deployment completion, merge queue, QA execution, private "
    "route qualification). Those paths read the authority's own GitHub App "
    "credentials, release checkouts and runtime identity, never the client's.",
    (
        "yoke_cli.config.credentialed_git:_run",
        "yoke_cli.config.credentialed_git_command:remote_url",
        "yoke_cli.config.github_git_credential_document:_default_machine_home",
        "yoke_cli.config.github_git_credential_document:machine_secrets_dir",
        "yoke_cli.config.github_git_credential_file:_assert_secure_parent",
        "yoke_cli.config.github_git_credential_file:_assert_stable_lock",
        "yoke_cli.config.github_git_credential_file:exclusive_lock",
        "yoke_cli.config.github_git_credential_file:lock_path",
        "yoke_cli.config.project_git_environment:non_interactive_git_env",
        "yoke_cli.config.project_git_process:run_network_git",
        _C + "check_hard_blocks:_branch_is_merged",
        _C + "checkout_ancestry:resolve_commits",
        _C + "check_hard_blocks:_git_root",
        _C + "gh_rest_transport_test_guard:block_live_test_call",
        _C + "github_app_control_plane:_resolved_open_file_path",
        _C + "github_app_control_plane:load_github_app_control_plane_config",
        _C + "github_app_control_plane:load_github_app_endpoint",
        _C + "github_app_control_plane:load_github_app_public_profile",
        _C + "project_file_at_commit:_from_checkout",
        _C + "qa_execution_environment_target:runtime_environment_name",
        _C + "session_private_route_qualification:_message_scope",
        _C + "session_private_route_qualification:_runtime_release",
    ),
)

EVALUATING_PROCESS_TELEMETRY = (
    "Disposable telemetry about the evaluating process: event emission and "
    "its isolation gate, observability settings, execution provenance, and "
    "an event's project or session attribution when the caller supplied "
    "none. On the authority these describe the authority, and attribution "
    "from its cwd resolves empty; no verdict reads them.",
    (
        "yoke_contracts.execution_provenance:_collect_execution_provenance",
        "yoke_contracts.execution_provenance:_git_sha",
        "yoke_contracts.machine_config.checkout:_git_main_checkout",
        "yoke_contracts.machine_config.checkout:main_checkout",
        "yoke_contracts.machine_config.schema_projects:_path_key",
        "yoke_contracts.machine_config.schema_projects:checkout_path_candidates",
        "yoke_contracts.machine_config.schema_projects:project_entry_for_checkout",
        "yoke_core.api.observability_debug:parse_debug_campaign",
        "yoke_core.api.observability_otel:service_name",
        "yoke_core.hooks.stdin:emit_session_hook_failed",
        _C + "emit_event:_registry_warning",
        _C + "emit_event:emit",
        _C + "events:emit_event",
        _C + "events_isolation:isolation_gate_blocks",
        _C + "function_unresolved_project:control_plevel_label",
        _C + "reflection_capture:_emit_persist_failed",
        _C + "reflection_capture:capture_reflections",
        _C + "yok_n_parser:item_argument_project",
    ),
)

AMBIENT_IDENTITY_FALLBACK = (
    "Session-identity channels of the evaluating process (environment, "
    "process anchors and ancestry, Cursor conversation maps). Hook policies "
    "pass the payload's session first: a relayed request is identity-stamped "
    "(relay_identity_guard.deny_unstamped_relay) and stamped ids win, "
    "workspace and subagent checks pass the payload id or env={}, and the "
    "session-cwd denial audit records these channels only as a diagnostic "
    "of the process that evaluated.",
    (
        "yoke_contracts.cursor_session_map:recorded_session_id_for_conversation",
        "yoke_contracts.cursor_session_map:resolve_container_from_subagent_transcript_layout",
        "yoke_contracts.cursor_session_map:resolve_mapped_session_id",
        "yoke_contracts.harness_family_identity:family_env_session_id",
        "yoke_contracts.harness_family_identity:resolve_env_session_id",
        "yoke_contracts.linux_process_snapshot:_stat",
        "yoke_contracts.linux_process_snapshot:process_command_name",
        "yoke_contracts.linux_process_snapshot:process_start_time",
        "yoke_contracts.linux_process_snapshot:process_table",
        "yoke_contracts.payload_session_fold:is_conversation_shaped_session_id",
        "yoke_contracts.process_ancestry:ps_lines",
        "yoke_contracts.session_execution:is_subagent_execution",
        "yoke_contracts.session_identity:_load_json",
        "yoke_contracts.session_identity:resolve_ambient_session_id",
        "yoke_contracts.session_identity:resolve_session_from_ancestry",
        _C + "session_ambient_identity:consult_identity_channels",
        _C + "session_ambient_identity:contested_anchor_session_ids",
        _C + "session_ambient_identity:fold_raw_identity",
        _C + "session_ambient_identity:resolve_ambient_session_id",
        _C + "session_ambient_identity:resolve_env_session_id",
        _C + "workspace_authority:_resolve_session_id",
    ),
)

CLIENT_PATH_CANONICALIZATION = (
    "Canonicalizes an absolute client path (Path.resolve, and expanduser on "
    "a path whose ~ the policy already expanded against the client's home "
    "fact). The authority holds no client checkouts, so a client path "
    "normalizes to its own spelling there. machine_home=None and "
    "scratch_root=None branches select the writing machine's own home, temp "
    "and scratch roots for in-process callers on that machine; every hook "
    'policy passes the client\'s facts instead ("" when absent).',
    (
        "yoke_contracts.free_paths:free_path_prefixes",
        "yoke_contracts.hook_runner.session_cwd:_valid_claude_job_tmp",
        "yoke_contracts.hook_runner.session_cwd:_valid_machine_home",
        "yoke_contracts.hook_runner.session_cwd:_valid_root",
        "yoke_contracts.machine_config.runtime:_machine_path",
        "yoke_contracts.machine_config.runtime:effective_temp_root",
        "yoke_contracts.machine_config.scratch_roots:fallback_scratch_root",
        _C + "command_workdir:_absolute",
        _C + "lint_lane_main_write_lanes:_under_worktrees",
        _C + "lint_lane_main_write_lanes:lane_equivalent_path",
        _C + "lint_session_cwd_home:_is_inside",
        _C + "lint_session_cwd_home:_selected_home",
        _C + "lint_session_cwd_home:is_external_reference_path",
        _C + "lint_session_cwd_home:is_sanctioned_installed_read_path",
        _C + "lint_session_cwd_path_authority:is_inside",
        _C + "lint_session_cwd_path_authority:is_inside_control_plane",
        _C + "lint_session_cwd_path_authority:is_yoke_watcher_capture_path",
        _C + "lint_session_cwd_path_authority:resolve_for_display",
        _C + "lint_session_cwd_target_extract:_resolve_target_paths",
        _C + "lint_session_cwd_target_extract:resolve_payload_cwd",
        _C + "path_claim_active_claim_lookup:_pick_chain_for_target",
        _C + "path_claim_bash_guard_narrative:target_under_active_worktree",
        _C + "path_claim_item_worktree_paths:universal_item_worktree_paths",
        _C + "path_claim_target_domain:cwd_in_claim_domain",
        _C + "path_claim_target_domain:domain_root_for_absolute_target",
        _C + "path_claim_target_domain:path_is_under",
        _C + "path_claim_target_resolver:evaluate_target",
        _C + "path_claim_task_session_coverage:_target_lane",
        _C + "worktree_paths:_normalize_repo_root",
    ),
)

UNRECORDED_LANE_PATH = (
    "Derives a lane path from the evaluating machine's checkout mapping and "
    "worktrees_dir setting, only for a lane row with no recorded path. "
    "Prepared lanes always record their path, so the authority never "
    "derives one.",
    (
        _C + "project_checkout_locations:checkout_for_project_id",
        _C + "runtime_settings:read_all",
    ),
)

LINT_CONFIG_WITHOUT_SNAPSHOT = (
    "Reads the evaluating process's own .yoke/lint-config only when the "
    "payload carries no lint-config snapshot. Every evaluation path ships "
    "the session checkout's snapshot (yoke_harness.hooks.client_facts), so "
    "the authority reaches this only for a request from an older client.",
    (
        "yoke_contracts.hook_runner.lint_policy:find_workspace_root",
        "yoke_contracts.hook_runner.lint_policy:parse_file",
        _C + "lint_config:_normalize_root",
        _C + "worktree_paths:_resolve_context_cwd",
        _C + "worktree_paths:_resolve_root",
        _C + "worktree_paths:_run",
    ),
)

OBSERVE_TELEMETRY_ENRICHMENT = (
    "Observe-pipeline enrichment of a recorded tool call: Codex exit status "
    "reconciled from its transcript, an item id read from a function-call "
    "input file, symlink-normalized dispatch directories and main-checkout "
    "attribution. No verdict reads these fields. On the authority the client "
    "files are absent and the enrichment stays empty, a known HTTPS "
    "telemetry gap recorded as a field note.",
    (
        _C + "observe_codex_transcript:_reconcile_codex_exit_code",
        _C + "observe_db_reads:repo_root_for_attribution",
        _C + "observe_function_call_refs:extract_function_call_item_id",
        _C + "observe_normalization:_normalize_dir",
        _C + "project_settings:checkout_root",
    ),
)

PACKAGE_DATA = (
    "Reads data files shipped inside the installed package, identical on "
    "every machine.",
    (_C + "builtin_workflow_canon:_load",),
)

REASONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    AUTHORITY_DATABASE,
    AUTHORITY_TRANSPORT,
    AUTHORITY_RELEASE_MACHINERY,
    EVALUATING_PROCESS_TELEMETRY,
    AMBIENT_IDENTITY_FALLBACK,
    CLIENT_PATH_CANONICALIZATION,
    UNRECORDED_LANE_PATH,
    LINT_CONFIG_WITHOUT_SNAPSHOT,
    OBSERVE_TELEMETRY_ENRICHMENT,
    PACKAGE_DATA,
)
