"""Client-local unmatched path-glob evaluation."""

from __future__ import annotations

from yoke_contracts.hook_runner.shell_guard_repairs import (
    RIPGREP_REPLACE_CHECK_ID,
    executing_shell,
    expanded_glob_path,
    find_unmatched_path_glob,
    glob_repair,
    ripgrep_replace_repair,
)
from yoke_contracts.hook_runner.shell_parse import ShellParse, parse_shell
from yoke_harness.hooks.local_policy_common import DENY, NOOP, PolicyResult


def _tool_input(payload: dict) -> dict:
    for key in ("tool_input", "toolInput", "input"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _command(payload: dict) -> str:
    tool_input = _tool_input(payload)
    for source in (tool_input, payload):
        for key in ("command", "cmd"):
            value = source.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def _execution_cwd(payload: dict) -> str:
    tool_input = _tool_input(payload)
    for source in (tool_input, payload):
        for key in ("workdir", "working_directory"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value
    raw_cwd = payload.get("cwd")
    if isinstance(raw_cwd, str) and raw_cwd.strip():
        return raw_cwd
    for key in ("project_dir", "workspace"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    roots = payload.get("workspace_roots")
    if isinstance(roots, list):
        return next(
            (value for value in roots if isinstance(value, str) and value.strip()),
            "",
        )
    return ""


def lint_unmatched_path_glob(payload: dict, shell: ShellParse) -> PolicyResult:
    """Deny an unmatched path glob only when the command shell is zsh.

    Globs are read from the command as written, before assignment
    substitution, so ``shell`` is reused only when it parsed that same text.
    """
    tool = payload.get("tool_name") or payload.get("toolName")
    if tool and tool != "Bash":
        return PolicyResult(NOOP)
    command = _command(payload)
    parsed = shell if shell.command == command else parse_shell(command)
    repair = ripgrep_replace_repair(parsed)
    if repair is not None:
        return PolicyResult(
            DENY,
            "BLOCKED: `rg -r` means `--replace`, not recursive search. "
            f"Repaired command: `{repair}`\n\nYoke check id: {RIPGREP_REPLACE_CHECK_ID}",
        )
    if executing_shell(payload) != "zsh":
        return PolicyResult(NOOP)
    cwd = _execution_cwd(payload)
    found = find_unmatched_path_glob(parsed, cwd)
    if found is None:
        return PolicyResult(NOOP)
    token, checked = found
    reason = (
        "BLOCKED: unquoted path glob matches no files after home and cwd resolution.\n\n"
        f"Detected: `{token}`\n"
        f"Checked pattern: `{expanded_glob_path(token, checked)}`\n"
        f"Checked tree: `{checked}`\n\n"
        "zsh NOMATCH aborts the command before the tool runs. Enumerate "
        "candidates with `rg --files`, or quote a pattern the tool consumes."
    )
    repair = glob_repair(parsed, token, checked)
    if repair is not None:
        repaired, matches = repair
        reason += "\n\nRepaired command: `" + repaired + "`"
        reason += "\nFiles matching the stem: " + (
            ", ".join(matches) if matches else "none"
        )
        reason += "\nIf `rg` is absent, enumerate tracked files with `git ls-files`."
    return PolicyResult(DENY, reason)


__all__ = ["lint_unmatched_path_glob"]
