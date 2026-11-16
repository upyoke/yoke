"""Which shells each shell-chain rule covers, read by client and engine dispatch.

Every shell tool runs the one ``Bash`` chain, and the shared parse hands each
rule the same segments whichever shell wrote the command. Rules about what a
command *does* (which program runs, which file it writes, which directory it
runs in) cover both shells. Rules that teach a Bash syntax idiom (backticks,
``$(...)`` inside double quotes, unmatched globs, ``| head``,
``2>/dev/null``, ``if ...; then`` status capture, ``sleep`` loops, temp-file
transforms, macOS privacy paths) cover only Bash, so a PowerShell command is
never refused for a shape it cannot have.

Each rule declares its shells here, beside :mod:`guard_scope`, so the relay
client can filter its local subset without importing engine modules.
:func:`shell_applicable_chain` refuses, naming the module, when a rule in a
shell chain has no declaration.
"""

from __future__ import annotations

from yoke_contracts.harness_shell_tools import SHELL_KIND_BASH, SHELL_KIND_POWERSHELL

_BOTH = frozenset({SHELL_KIND_BASH, SHELL_KIND_POWERSHELL})
_BASH = frozenset({SHELL_KIND_BASH})

_COVERS_BOTH = (
    "lint_db_cmd",
    "lint_main_commit",
    "lint_tc_label",
    "lint_raw_pytest_full_suite",
    "lint_watcher_module_form",
    "lint_headless_watcher_timeout",
    "lint_subagent_background",
    "lint_subagent_fleet_messaging",
    "lint_session_cwd",
    "lint_lane_main_write",
    "lint_workspace_cwd_match",
    "path_claim_bash_guard",
    "lint_no_agent_runtime_api_import_from_c",
    "lint_no_agent_curl_against_yoke_api",
    "lint_no_agent_session_end",
    "lint_claim_ownership_mutations",
    "lint_git_stash_arg_order",
    "lint_destructive_git",
    "db_error_hook",
    "observe_pre",
    "observe",
)
_COVERS_BASH = (
    "lint_long_command_polling",
    "lint_pipe_to_truncator",
    "lint_if_status_capture",
    "lint_structured_field_transform_shell",
    "lint_yoke_adapter_stderr_visibility",
    "lint_shell_backtick_search",
    "lint_yoke_quoted_shell_substitution",
    "lint_local_privacy",
    "lint_unmatched_path_glob",
)

GUARD_SHELLS: dict[str, frozenset[str]] = {
    f"yoke_core.domain.{name}": shells
    for names, shells in ((_COVERS_BOTH, _BOTH), (_COVERS_BASH, _BASH))
    for name in names
}

_RULE_PREFIXES = ("lint_", "path_claim_", "observe", "db_error_hook", "hint_")


def guard_shells(module_id: str) -> frozenset[str] | None:
    """Shells a rule covers; ``None`` for a shell-neutral non-rule module.

    A ``yoke_core.domain`` rule without a declaration is a named refusal.
    """
    shells = GUARD_SHELLS.get(module_id)
    if shells is None and module_id.startswith("yoke_core.domain."):
        name = module_id.removeprefix("yoke_core.domain.")
        if name.startswith(_RULE_PREFIXES):
            raise ValueError(
                f"hook_guard_shells_missing: {module_id}; declare the shells it covers "
                "in yoke_contracts.hook_runner.guard_shells and retry"
            )
    return shells


def shell_applicable_chain(chain: list[str], shell_kind: str | None) -> list[str]:
    """Drop rules that do not cover ``shell_kind``; ``None`` keeps the chain."""
    if shell_kind is None:
        return list(chain)
    kept: list[str] = []
    for module_id in chain:
        shells = guard_shells(module_id)
        if shells is None or shell_kind in shells:
            kept.append(module_id)
    return kept


__all__ = ["GUARD_SHELLS", "guard_shells", "shell_applicable_chain"]
