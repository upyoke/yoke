"""Catalog of mode-controlled hook guards."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


REMOTE_CLAUDE_CLI_GUARD = "lint_db_cmd_remote_claude_cli"
DB_COMMAND_STABLE_CHECK_ID = "lint-sqlite-cmd"
NESTED_CLAUDE_CLI_CHECK_ID = "lint-nested-claude-cli"
REMOTE_CLAUDE_CLI_CHECK_ID = "lint-remote-claude-cli"
_MODULE_PREFIX = "yoke_core.domain."


@dataclass(frozen=True)
class GuardSpec:
    """One mode-controlled denier guard in the hook chain."""

    guard: str
    module: str
    protected: bool
    description: str
    check_id: str
    accepted_check_ids: Tuple[str, ...] = ()
    aliases: Tuple[str, ...] = ()
    module_aliases: Tuple[str, ...] = ()
    compatibility_id: str = ""

    @property
    def report_check_ids(self) -> Tuple[str, ...]:
        """All check ids this registered guard is allowed to report."""
        return (self.check_id, *self.accepted_check_ids)


GUARD_CATALOG: Tuple[GuardSpec, ...] = (
    GuardSpec(
        "lint_db_cmd",
        f"{_MODULE_PREFIX}lint_db_cmd",
        False,
        "Refuse raw sqlite3 CLI against the control-plane DB.",
        check_id=DB_COMMAND_STABLE_CHECK_ID,
        accepted_check_ids=(
            NESTED_CLAUDE_CLI_CHECK_ID,
            REMOTE_CLAUDE_CLI_CHECK_ID,
        ),
        compatibility_id=DB_COMMAND_STABLE_CHECK_ID,
    ),
    GuardSpec(
        REMOTE_CLAUDE_CLI_GUARD,
        f"{_MODULE_PREFIX}lint_db_cmd.remote_claude_cli",
        False,
        "Refuse Claude CLI invocations embedded in remote SSH commands.",
        check_id=REMOTE_CLAUDE_CLI_CHECK_ID,
    ),
    GuardSpec(
        "lint_event_registry",
        f"{_MODULE_PREFIX}lint_event_registry",
        False,
        "Refuse Bash that emits unregistered/retired event names.",
        check_id="unregistered_event",
    ),
    GuardSpec(
        "lint_main_commit",
        f"{_MODULE_PREFIX}lint_main_commit",
        True,
        "Refuse implementation commits on the main branch.",
        check_id="impl_on_main",
    ),
    GuardSpec(
        "lint_tc_label",
        f"{_MODULE_PREFIX}lint_tc_label",
        False,
        "Enforce the tool-call label convention on Bash.",
        check_id="lint-tc-label",
    ),
    GuardSpec(
        "lint_long_command_polling",
        f"{_MODULE_PREFIX}lint_long_command_polling",
        False,
        "Refuse same-capture polling loops on a running long command.",
        check_id="long_command_polling",
    ),
    GuardSpec(
        "lint_monitor_watcher_tail",
        f"{_MODULE_PREFIX}lint_monitor_watcher_tail",
        False,
        "Require sentinel-aware Monitor tails for watcher captures.",
        check_id="lint-monitor-watcher-tail",
    ),
    GuardSpec(
        "lint_pipe_to_truncator",
        f"{_MODULE_PREFIX}lint_pipe_to_truncator",
        False,
        "Refuse piping a live long command into tail/head.",
        check_id="lint-pipe-to-truncator",
    ),
    GuardSpec(
        "lint_raw_pytest_full_suite",
        f"{_MODULE_PREFIX}lint_raw_pytest_full_suite",
        False,
        "Refuse a raw pytest sweep over the whole verification "
        "surface; it bypasses the machine-wide test-gate "
        "admission slot.",
        check_id="lint-raw-pytest-full-suite",
    ),
    GuardSpec(
        "lint_watcher_module_form",
        f"{_MODULE_PREFIX}lint_watcher_module_form",
        False,
        "Refuse legacy watcher module forms when a yoke CLI adapter exists.",
        check_id="lint-watcher-module-form",
    ),
    GuardSpec(
        "lint_if_status_capture",
        f"{_MODULE_PREFIX}lint_if_status_capture",
        False,
        "Refuse `$?` capture immediately after an `if` compound.",
        check_id="lint-if-status-capture",
    ),
    GuardSpec(
        "lint_subagent_background",
        f"{_MODULE_PREFIX}lint_subagent_background",
        False,
        "Refuse background/Monitor backgrounding tools in subagent context.",
        check_id="subagent_background",
    ),
    GuardSpec(
        "lint_subagent_fleet_messaging",
        f"{_MODULE_PREFIX}lint_subagent_fleet_messaging",
        True,
        "Refuse Fleet send/ack commands from subagent execution contexts.",
        check_id="lint-subagent-fleet-messaging",
    ),
    GuardSpec(
        "lint_session_cwd",
        f"{_MODULE_PREFIX}lint_session_cwd",
        False,
        "Confine writes to the session's claimed worktree / allowlist.",
        check_id="lint-session-cwd",
    ),
    GuardSpec(
        "lint_lane_main_write",
        f"{_MODULE_PREFIX}lint_lane_main_write",
        False,
        "Refuse source writes to main checkout while an implementation lane is held.",
        check_id="lint-lane-main-write",
    ),
    GuardSpec(
        "lint_workspace_cwd_match",
        f"{_MODULE_PREFIX}lint_workspace_cwd_match",
        False,
        "Refuse cross-checkout pytest/render/test-runner Bash invocations.",
        check_id="lint-workspace-cwd-match",
    ),
    GuardSpec(
        "path_claim_bash_guard",
        f"{_MODULE_PREFIX}path_claim_bash_guard",
        False,
        "Enforce path-claim coverage for claim-mutating Bash.",
        check_id="path-claim-bash-guard",
    ),
    GuardSpec(
        "lint_structured_field_transform_shell",
        f"{_MODULE_PREFIX}lint_structured_field_transform_shell",
        False,
        "Refuse read-transform-in-shell-then-pipe-back structured-field edits.",
        check_id="structured_field_transform_choreography",
    ),
    GuardSpec(
        "lint_shell_quoted_function_payload",
        f"{_MODULE_PREFIX}lint_shell_quoted_function_payload",
        False,
        "Refuse hand-quoted JSON payloads and adapter shell-choreography.",
        check_id="shell_quoted_function_payload",
    ),
    GuardSpec(
        "lint_yoke_adapter_stderr_visibility",
        f"{_MODULE_PREFIX}lint_yoke_adapter_stderr_visibility",
        False,
        "Keep diagnostic stderr visible on state-changing Yoke adapters.",
        check_id="lint-yoke-adapter-stderr-visibility",
    ),
    GuardSpec(
        "lint_shell_backtick_search",
        f"{_MODULE_PREFIX}lint_shell_backtick_search",
        False,
        "Refuse grep/rg search text with backticks inside double quotes.",
        check_id="lint-shell-backtick-search",
    ),
    GuardSpec(
        "lint_local_privacy",
        f"{_MODULE_PREFIX}lint_local_privacy",
        True,
        "Refuse local GUI automation and privacy-managed filesystem access.",
        check_id="lint-local-privacy",
    ),
    GuardSpec(
        "lint_unmatched_path_glob",
        f"{_MODULE_PREFIX}lint_unmatched_path_glob",
        False,
        "Refuse unquoted path globs that match no files; teach rg --files.",
        check_id="lint-unmatched-path-glob",
    ),
    GuardSpec(
        "lint_no_agent_runtime_api_import_from_c",
        f"{_MODULE_PREFIX}lint_no_agent_runtime_api_import_from_c",
        True,
        'Refuse `python3 -c "from runtime..."` agent reach-in.',
        check_id="python_runtime_import_in_tmp",
    ),
    GuardSpec(
        "lint_no_agent_curl_against_yoke_api",
        f"{_MODULE_PREFIX}lint_no_agent_curl_against_yoke_api",
        True,
        "Refuse curl against the local Yoke API surface.",
        check_id="lint-no-agent-curl-against-yoke-api",
    ),
    GuardSpec(
        "lint_no_agent_session_end",
        f"{_MODULE_PREFIX}lint_no_agent_session_end",
        True,
        "Refuse agent-context session-end API bypass.",
        check_id="lint-no-agent-session-end",
    ),
    GuardSpec(
        "lint_claim_ownership_mutations",
        f"{_MODULE_PREFIX}lint_claim_ownership_mutations",
        True,
        "Refuse claim/ownership mutations that bypass the sanctioned surface.",
        check_id="claim_ownership_mutation",
    ),
    GuardSpec(
        "lint_git_stash_arg_order",
        f"{_MODULE_PREFIX}lint_git_stash_arg_order",
        False,
        "Refuse `git stash push` with a message flag after `--`.",
        check_id="lint-git-stash-arg-order",
    ),
    GuardSpec(
        "lint_destructive_git",
        f"{_MODULE_PREFIX}lint_destructive_git",
        True,
        "Refuse git verbs that would wipe uncommitted/untracked local state.",
        check_id="lint-destructive-git",
    ),
)


__all__ = [
    "DB_COMMAND_STABLE_CHECK_ID",
    "GUARD_CATALOG",
    "GuardSpec",
    "NESTED_CLAUDE_CLI_CHECK_ID",
    "REMOTE_CLAUDE_CLI_CHECK_ID",
    "REMOTE_CLAUDE_CLI_GUARD",
]
