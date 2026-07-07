# Carve-out: harness split (Decision 1) + guardrails (Decision 2) — YOK-1902

Verified against the live tree (Agent C). 60 harness modules. The client/authority
boundary is already drawn in code by the Phase-3 hook-relay work; this is physical
separation + 11 function-level splits.

## → yoke_contracts (pure types/shapes/ordering)

`hook_runner.types`, `hook_runner.remote_policy` (`LOCAL_STATE_POLICIES`,
`RunControls`), `hook_runner.chain_registry`, `hook_helpers_model`,
`hook_helpers_identity`, `codex.codex_model`, `codex.codex_hooks_model`, and
`runtime.api.domain.harness_hook_ordering` (stdlib-pure; moves here with
`chain_registry`). New home: `yoke_contracts.hook_runner.*` / `.codex.*` /
top-level `hook_helpers_model`/`hook_helpers_identity`.

## → yoke_harness (client-adapter glue)

`claude.adapter`, `claude.merge_settings`, `codex.adapter`, `codex.codex_entry`,
`codex.codex_open_app`, `codex.codex_hooks_payload`, **`codex.codex_db_resolution`**
(CORRECTION: client — resolves a DB *path string* via `yoke_connected_env.load_active`,
no connection), `hook_helpers` (barrel), `hook_helpers_markers`,
`hook_runner.{identity,deadline,mode_gate,decision_render,adapter_capability,
capability_resolve,run_tail,runner,typed_dispatch,subprocess_policy,session_workspace
(PURE — os/shlex only),target,session_lifecycle_client,session_dispatch_codex_lifecycle,
session_dispatch_first_prompt,__main__}`. New home: `yoke_harness.*` mirroring the
`claude/`, `codex/`, `hook_runner/` layout.

## → yoke_core (authority)

`harness_sessions`, `harness_sessions_claims`, `harness_sessions_claims_acquire`,
`harness_sessions_event_emit`, `harness_sessions_focus`, `harness_sessions_inventory`,
`harness_sessions_lifecycle`, `hook_runner_register_identity`,
`hook_runner.remote_lifecycle`, `hook_runner.resume_block_dispatch`,
`hook_runner.session_end_cleanup`, session orientation helpers that need
authority-side reads, `bootstrap_packets` (live packet render). New home:
`yoke_core.sessions.*` (the authority half of today's harness session logic).

## SPLIT files — function-level boundaries (the real hand-work)

The core half reaches client callers only via the transport (`call_dispatcher`).

| Old module | → harness half | → core half |
| :-- | :-- | :-- |
| `hook_runner.remote_entry` (167) | `evaluate_local_subset`, `LocalSubsetEvaluation` (runs LOCAL_STATE_POLICIES subset, fail-open) | `evaluate_remote`, `RemoteEvaluation` (server full-pipeline; both call `run_event`, differ by `remote` flag) |
| `hook_runner_register` (292) | `_record_process_anchor` (file-write via `json_helper`, client-safe), `_register_from_hook`/`ensure_registered_from_hook` orchestration shells | `_register_in_process` (`db_helpers.connect()` + `register_session`) |
| `hook_helpers_session_id` (238) | `get_session_id` (ambient), `find_project_root`, `resolve_yoke_db`, `parse_hook_json` | `resolve_dispatch_context` (`SELECT FROM epic_dispatch_chains` + `items`) |
| `hook_helpers_heartbeat` (152) | `evaluate`, `_backfill_session` relay shell, `_fallback_*` | `_heartbeat_session` (`db_backend.connect()` + `heartbeat`) |
| `hook_runner.session_dispatch` (333 — over 330, split while moving) | `evaluate`, all `_render_*`/`_run_*` orientation renderers, `_bootstrap_lines`, `_git_line`, `_decision` | (cleanup is a thin call to `run_session_end_cleanup`, already in `session_end_cleanup` core — route over transport; NO new core module) |
| `hook_runner.telemetry` (350) | re-export barrel (`build_denial_*`, identity re-exports, `session_service_client_path`) | `_emit_hook_event`, `emit_hook_guardrail_evaluated`, `emit_hook_execution_failed`, `emit_hook_dispatch_telemetry`, `flush_hook_telemetry`, `_flush_records` |
| `hook_runner.denial` (125) | `build_denial_payload`, `build_denial_context` | `emit_denial_event` |
| `hook_runner.stdin` (166) | `bounded_stdin_read`, `parse_json_payload` | `emit_session_hook_failed`, `emit_harness_session_sent_first_user_prompt_submit` |
| `bootstrap` (346) | orientation render: `render_compact/full/required_files/install`, `load_spec`, `read_file`, `doctrine_short`, `list_skills`, `resolve_skill_path`, `main`, `run_command` | packet content → `bootstrap_packets` (core; fetched as a transport packet bundle) |
| `hook_runner.service_client` (321 — 3-way) | path/env plumbing (`resolve_repo_root`, `session_service_client_path`, `target_*_env*`, `_target_cwd`) **+** `register_session`/`touch_session` (today subprocess the server CLI → become transport calls) | `refresh_session_model_if_placeholder` (`db_backend.connect()` at L267 + `UPDATE harness_sessions` + emit) — the ONE true direct-DB function |

## Decision 2 — guardrails (16 PreToolUse lints, authoritative: `harness_hook_ordering.HOOK_ORDERING` L134-151)

Home: `yoke_harness/guardrails/`.

**PURE-LOCAL (11 — move as-is):** `lint_destructive_git`,
`lint_python_runtime_import_in_tmp`, `lint_workspace_cwd_match`,
`lint_subagent_background`, `lint_db_cmd`, `lint_tc_label`, `lint_pipe_to_truncator`,
`lint_structured_field_transform_shell`, `lint_shell_quoted_function_payload`,
`lint_no_agent_runtime_api_import_from_c`, `lint_no_agent_curl_against_yoke_api`.
(Several name `service_client`/`call_dispatcher` only in denial-message strings or as
forbidden-import-target patterns — confirmed NOT live calls.)

**NEEDS CACHED-READ CONVERSION (2 — direct `db_helpers.connect()` today):**
- `lint_session_cwd` (`lint_session_cwd.py:96` + `lint_session_cwd_validate.py:217`):
  reads `claimed_worktrees(conn, session_id)` + `SELECT status FROM items`. Fail-open.
- `lint_long_command_polling` (`..._evaluate.py:79` + `..._monitor_duplicate.py:97`):
  reads `session_tool_calls WHERE tool_name IN ('Bash','Monitor')`. Fail-open.

**PRECEDENT (1 — already dispatcher-mediated, no conversion):** `lint_main_commit`
(`lint_main_commit.py:124-130` `call_dispatcher(function_id="items.list.run", ...)` +
`lint_main_commit_strategy_freshness.py:121` for `strategy_docs`). The line-115
`connect()` is a historical comment, not a live call. This IS the template.

**Coordination split:** the lint *logic* (pure path-string matching in
`lint_session_cwd_validate`, `_target_extract`, `_path_authority`) → harness; the
DB-backed reads (`session_claimed_worktrees`) STAY core and become API reads. The
codemod must NOT drag `session_claimed_worktrees` into the harness package.

## yoke_harness public surface (shallow exports)

`evaluate_local_subset` (relay entry), `merge_allow_stdout`, `detect_executor`/
`is_codex`/`canonical_harness_id`, `resolve_capability`, `HookDeadline`/
`resolve_total_timeout_ms`, the `guardrails` package (PreToolUse entrypoints),
`bootstrap.main`, `codex_entry`/`codex_open_app`. Invariant: `yoke_harness` imports
only `yoke_contracts` + the transport client (+ optionally `yoke_cli` client
substrate); NEVER `yoke_core`/`runtime.api.*`.

## Coordination confirmations (verified)

- `cli.yoke_hooks_relay` imports ONLY client surfaces (`hook_helpers_identity`,
  `hook_runner.deadline`, `codex.codex_hooks_payload`,
  `hook_runner.remote_entry.evaluate_local_subset`, `decision_render.merge_allow_stdout`)
  — boundary consistent; the `evaluate_local_subset` it calls is the harness half of
  the `remote_entry` split.
- The harness authority halves (core registration, emit, refresh, cleanup) reach
  core via the same `call_dispatcher` transport chokepoint.
- Tests (49) + conftests move with whichever package owns the module under test.
