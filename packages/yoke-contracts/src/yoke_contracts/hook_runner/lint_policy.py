"""Shared hook guard policy contract.

The project-local ``.yoke/lint-config`` file is client authority: hook
evaluation may be split between a local product client and an HTTPS server, but
the operator's checked-out policy must travel with the hook payload and be
resolved identically on both sides.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Tuple

DENY = "deny"
WARN = "warn"
VALID_MODES = (DENY, WARN)
ALLOW_WARN_TOKEN = "# allow-warn"
CONFIG_RELPATH = (".yoke", "lint-config")
SNAPSHOT_PAYLOAD_KEY = "_yoke_lint_config"
REMOTE_CLAUDE_CLI_GUARD = "lint_db_cmd_remote_claude_cli"
_MODULE_PREFIX = "yoke_core.domain."


@dataclass(frozen=True)
class GuardSpec:
    """One mode-controlled denier guard in the hook chain."""

    guard: str
    module: str
    protected: bool
    description: str
    aliases: Tuple[str, ...] = ()
    module_aliases: Tuple[str, ...] = ()


GUARD_CATALOG: Tuple[GuardSpec, ...] = (
    GuardSpec("lint_db_cmd", f"{_MODULE_PREFIX}lint_db_cmd", False,
              "Refuse raw sqlite3 CLI against the control-plane DB.",
              aliases=("lint_sqlite_cmd",),
              module_aliases=(f"{_MODULE_PREFIX}lint_sqlite_cmd",)),
    GuardSpec(REMOTE_CLAUDE_CLI_GUARD,
              f"{_MODULE_PREFIX}lint_db_cmd.remote_claude_cli", False,
              "Refuse Claude CLI invocations embedded in remote SSH commands."),
    GuardSpec("lint_event_registry", f"{_MODULE_PREFIX}lint_event_registry", False,
              "Refuse Bash that emits unregistered/retired event names."),
    GuardSpec("lint_main_commit", f"{_MODULE_PREFIX}lint_main_commit", True,
              "Refuse implementation commits on the main branch."),
    GuardSpec("lint_tc_label", f"{_MODULE_PREFIX}lint_tc_label", False,
              "Enforce the tool-call label convention on Bash."),
    GuardSpec("lint_long_command_polling", f"{_MODULE_PREFIX}lint_long_command_polling", False,
              "Refuse same-capture polling loops on a running long command."),
    GuardSpec("lint_pipe_to_truncator", f"{_MODULE_PREFIX}lint_pipe_to_truncator", False,
              "Refuse piping a live long command into tail/head."),
    GuardSpec("lint_subagent_background", f"{_MODULE_PREFIX}lint_subagent_background", False,
              "Refuse background/Monitor backgrounding tools in subagent context."),
    GuardSpec("lint_session_cwd", f"{_MODULE_PREFIX}lint_session_cwd", False,
              "Confine writes to the session's claimed worktree / allowlist."),
    GuardSpec("lint_workspace_cwd_match", f"{_MODULE_PREFIX}lint_workspace_cwd_match", False,
              "Refuse cross-checkout pytest/render/test-runner Bash invocations."),
    GuardSpec("path_claim_bash_guard", f"{_MODULE_PREFIX}path_claim_bash_guard", False,
              "Enforce path-claim coverage for claim-mutating Bash."),
    GuardSpec("lint_structured_field_transform_shell",
              f"{_MODULE_PREFIX}lint_structured_field_transform_shell", False,
              "Refuse read-transform-in-shell-then-pipe-back structured-field edits."),
    GuardSpec("lint_shell_quoted_function_payload",
              f"{_MODULE_PREFIX}lint_shell_quoted_function_payload", False,
              "Refuse hand-quoted JSON payloads and adapter shell-choreography."),
    GuardSpec("lint_shell_backtick_search",
              f"{_MODULE_PREFIX}lint_shell_backtick_search", False,
              "Refuse grep/rg search text with backticks inside double quotes."),
    GuardSpec("lint_no_agent_runtime_api_import_from_c",
              f"{_MODULE_PREFIX}lint_no_agent_runtime_api_import_from_c", True,
              "Refuse `python3 -c \"from runtime...\"` agent reach-in."),
    GuardSpec("lint_no_agent_curl_against_yoke_api",
              f"{_MODULE_PREFIX}lint_no_agent_curl_against_yoke_api", True,
              "Refuse curl against the local Yoke API surface."),
    GuardSpec("lint_no_agent_session_end", f"{_MODULE_PREFIX}lint_no_agent_session_end", True,
              "Refuse agent-context session-end API bypass."),
    GuardSpec("lint_claim_ownership_mutations",
              f"{_MODULE_PREFIX}lint_claim_ownership_mutations", True,
              "Refuse claim/ownership mutations that bypass the sanctioned surface."),
    GuardSpec("lint_git_stash_arg_order", f"{_MODULE_PREFIX}lint_git_stash_arg_order", False,
              "Refuse `git stash push` with a message flag after `--`."),
    GuardSpec("lint_destructive_git", f"{_MODULE_PREFIX}lint_destructive_git", True,
              "Refuse git verbs that would wipe uncommitted/untracked local state."),
)

_BY_GUARD: dict[str, GuardSpec] = {}
_BY_MODULE: dict[str, GuardSpec] = {}
for _spec in GUARD_CATALOG:
    _BY_GUARD[_spec.guard] = _spec
    for _alias in _spec.aliases:
        _BY_GUARD[_alias] = _spec
    _BY_MODULE[_spec.module] = _spec
    for _alias in _spec.module_aliases:
        _BY_MODULE[_alias] = _spec


def short_id(guard_or_module: str) -> str:
    return guard_or_module.rsplit(".", 1)[-1] if "." in guard_or_module else guard_or_module


def spec_for(guard_or_module: str) -> GuardSpec | None:
    return _BY_MODULE.get(guard_or_module) or _BY_GUARD.get(short_id(guard_or_module))


def is_registered(guard_or_module: str) -> bool:
    return spec_for(guard_or_module) is not None


def parse_text(text: str) -> dict[str, tuple[str, bool]]:
    """Parse lint-config text into ``guard -> (mode, allow_warn_token)``."""
    parsed: dict[str, tuple[str, bool]] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, rest = line.partition("=")
        key = key.strip()
        if not key:
            continue
        allow_warn = ALLOW_WARN_TOKEN in rest
        value = rest.split("#", 1)[0].strip().lower()
        if value in VALID_MODES:
            parsed[key] = (value, allow_warn)
    return parsed


def parse_file(path: str | os.PathLike[str] | None) -> dict[str, tuple[str, bool]]:
    if not path:
        return {}
    selected = Path(path)
    if not selected.is_file():
        return {}
    try:
        return parse_text(selected.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return {}


def resolve_mode_from_entries(
    guard_or_module: str,
    entries: Mapping[str, tuple[str, bool]],
) -> str:
    spec = spec_for(guard_or_module)
    if spec is None:
        return DENY
    entry = entries.get(spec.guard)
    if entry is None:
        for alias in spec.aliases:
            entry = entries.get(alias)
            if entry is not None:
                break
    if entry is None:
        return DENY
    mode, allow_warn = entry
    if mode == WARN and spec.protected and not allow_warn:
        return DENY
    return mode


def snapshot_from_entries(
    entries: Mapping[str, tuple[str, bool]],
) -> dict[str, dict[str, object]]:
    return {
        guard: {"mode": mode, "allow_warn": bool(allow_warn)}
        for guard, (mode, allow_warn) in entries.items()
        if mode in VALID_MODES
    }


def entries_from_snapshot(value: object) -> dict[str, tuple[str, bool]]:
    if not isinstance(value, Mapping):
        return {}
    entries: dict[str, tuple[str, bool]] = {}
    for key, raw in value.items():
        if not isinstance(key, str):
            continue
        if isinstance(raw, Mapping):
            mode = str(raw.get("mode") or "").lower()
            allow_warn = bool(raw.get("allow_warn"))
        else:
            mode = str(raw).lower()
            allow_warn = False
        if mode in VALID_MODES:
            entries[key] = (mode, allow_warn)
    return entries


def snapshot_from_file(path: str | os.PathLike[str] | None) -> dict[str, dict[str, object]]:
    return snapshot_from_entries(parse_file(path))


def resolve_mode_from_snapshot(guard_or_module: str, snapshot: object) -> str:
    return resolve_mode_from_entries(guard_or_module, entries_from_snapshot(snapshot))


def find_workspace_root(start: str | os.PathLike[str] | None = None) -> Optional[Path]:
    for key in ("YOKE_TARGET_REPO_ROOT", "CLAUDE_PROJECT_DIR", "CODEX_PROJECT_DIR", "YOKE_REPO_ROOT"):
        value = os.environ.get(key)
        if value:
            return Path(value).expanduser().resolve(strict=False)
    current = Path(start or os.getcwd()).expanduser().resolve(strict=False)
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / CONFIG_RELPATH[0] / CONFIG_RELPATH[1]).is_file():
            return candidate
    return None


def config_path_for_root(root: str | os.PathLike[str] | None = None) -> Optional[Path]:
    base = Path(root).expanduser().resolve(strict=False) if root else find_workspace_root()
    return base / CONFIG_RELPATH[0] / CONFIG_RELPATH[1] if base else None


def snapshot_from_workspace(
    *,
    root: str | os.PathLike[str] | None = None,
    start: str | os.PathLike[str] | None = None,
) -> dict[str, dict[str, object]]:
    base = config_path_for_root(root) if root else None
    if base is None and root is None:
        found = find_workspace_root(start)
        base = found / CONFIG_RELPATH[0] / CONFIG_RELPATH[1] if found else None
    path = base
    return snapshot_from_file(path)


def render_lint_config() -> str:
    lines = [
        "# Yoke hook-guard enforcement modes - project-local policy.",
        "# One line per guard: <guard>=deny|warn  (deny blocks; warn observes only).",
        "# Protected guards (security/integrity) refuse warn unless the line ends",
        f"# with the `{ALLOW_WARN_TOKEN}` override token.",
        "",
    ]
    for spec in GUARD_CATALOG:
        protection = (
            "  [protected: warn needs `# allow-warn`]" if spec.protected else ""
        )
        lines.append(f"# {spec.description}{protection}")
        if spec.aliases:
            aliases = ", ".join(spec.aliases)
            lines.append(f"# Legacy stable config aliases still accepted: {aliases}")
        lines.append(f"{spec.guard}={DENY}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "ALLOW_WARN_TOKEN", "CONFIG_RELPATH", "DENY", "GUARD_CATALOG",
    "GuardSpec", "REMOTE_CLAUDE_CLI_GUARD", "SNAPSHOT_PAYLOAD_KEY", "WARN",
    "config_path_for_root", "entries_from_snapshot", "find_workspace_root",
    "is_registered", "parse_file", "parse_text", "render_lint_config",
    "resolve_mode_from_entries", "resolve_mode_from_snapshot",
    "short_id", "snapshot_from_entries", "snapshot_from_file",
    "snapshot_from_workspace", "spec_for",
]
