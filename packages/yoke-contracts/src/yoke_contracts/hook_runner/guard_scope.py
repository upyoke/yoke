"""Guard applicability shared by client-local and engine hook dispatch."""

from __future__ import annotations

from enum import Enum


class GuardScope(str, Enum):
    MACHINE = "machine"
    PROJECT = "project"
    LANE = "lane"


_MACHINE = (
    "lint_shell_backtick_search",
    "lint_local_privacy",
    "lint_unmatched_path_glob",
)
_PROJECT = (
    "lint_if_status_capture",
    "lint_git_stash_arg_order",
    "lint_db_cmd",
    "lint_db_cmd.nested_claude_cli",
    "lint_db_cmd.remote_claude_cli",
    "lint_main_commit",
    "lint_tc_label",
    "lint_long_command_polling",
    "lint_monitor_watcher_tail",
    "lint_pipe_to_truncator",
    "lint_raw_pytest_full_suite",
    "lint_watcher_module_form",
    "lint_headless_watcher_timeout",
    "lint_subagent_background",
    "lint_subagent_fleet_messaging",
    "lint_workspace_cwd_match",
    "lint_structured_field_transform_shell",
    "lint_yoke_adapter_stderr_visibility",
    "lint_yoke_quoted_shell_substitution",
    "lint_no_agent_runtime_api_import_from_c",
    "lint_no_agent_curl_against_yoke_api",
    "lint_no_agent_session_end",
    "lint_claim_ownership_mutations",
    "lint_destructive_git",
    "lint_write_path",
    "lint_python_runtime_import_in_tmp",
    "hint_file_line_limit_approach",
    "db_error_hook",
    "turn_end_promised_work_gate",
)
_LANE = (
    "lint_session_cwd",
    "lint_lane_main_write",
    "path_claim_bash_guard",
    "path_claim_pre_edit_guard",
)
GUARD_SCOPES = {
    f"yoke_core.domain.{name}": scope
    for names, scope in (
        (_MACHINE, GuardScope.MACHINE),
        (_PROJECT, GuardScope.PROJECT),
        (_LANE, GuardScope.LANE),
    )
    for name in names
}


def guard_scope(module_id: str) -> GuardScope | None:
    """Non-guards retain their delivery contract; guards need an explicit tag."""
    scope = GUARD_SCOPES.get(module_id)
    if scope is None and module_id.startswith("yoke_core.domain."):
        name = module_id.removeprefix("yoke_core.domain.")
        if name.startswith(("lint_", "path_claim_")) or name.endswith("_gate"):
            raise ValueError(
                f"hook_guard_scope_missing: {module_id}; declare machine, project or lane "
                "applicability in yoke_contracts.hook_runner.guard_scope and retry"
            )
    return scope


def applicable_chain(chain: list[str], project_id: int | None) -> list[str]:
    """Lane guards check their own authority, including on managed main."""
    return [
        module_id
        for module_id in chain
        if guard_scope(module_id) in (None, GuardScope.MACHINE)
        or project_id is not None
    ]
