"""Hook command and entry shapes shared by project and machine-wide hooks.

Every Yoke hook entry, in a project config or a harness's user config, runs
one ``yoke hook evaluate <Verb>`` command through the same bounded PATH and
the same ``YOKE_ROOT`` expression. Project hooks and machine-wide hooks differ
only in the ``YOKE_HOOK_CONFIG_OWNER`` value they carry, which is how the
step-aside rule tells them apart. The three native entry shapes stay here as
thin, named, co-located branches.

Cursor commands stay clear of the byte sequences its JSONC hook loader
mishandles; see
:data:`yoke_contracts.cursor_hook_command_bytes.CURSOR_HOOK_COMMAND_BYTE_REASON`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

from yoke_contracts.harness_machine_hooks import (
    RETIRED_USER_HOOK_MARKERS,
    HarnessMachineHooks,
    entry_commands,
    MachineHookEvent,
)
from yoke_contracts.hook_runner.config_owner import CONFIG_OWNER_ENV_VAR
from yoke_harness.hooks.shell_command import hook_shell_command

YOKE_HOOK_EVALUATE = "yoke hook evaluate"
ROOT_VARIABLE = "YOKE_ROOT"

#: The folder a hook evaluates against: the session's folder, never a pinned
#: checkout, so one rendered command serves every lane and every project.
HOOK_ROOT_EXPRESSIONS: Mapping[str, str] = {
    "claude-code": "${CLAUDE_PROJECT_DIR:-$PWD}",
    "codex": "${YOKE_ROOT:-$PWD}",
    "cursor": "${CURSOR_PROJECT_DIR:-$PWD}",
}

# Codex and Cursor hook subprocesses do not reliably carry a harness signal,
# so their commands pin the executor family (and Codex's provider) directly.
_IDENTITY_ENV: Mapping[str, str] = {
    "claude-code": "",
    "codex": "YOKE_EXECUTOR=codex YOKE_PROVIDER=openai",
    "cursor": "YOKE_EXECUTOR=cursor",
}

#: Cursor kills an entry after ``timeout`` seconds; an explicit ceiling keeps
#: a slow transport from meeting an undocumented platform default.
CURSOR_HOOK_TIMEOUT_S = 30

# Worktree path segments the Cursor fallback peels, held in variables so the
# rendered command never spells a JSONC comment delimiter.
_WORKTREE_SEGMENT = "/.worktrees/"
_CLAUDE_WORKTREE_SEGMENT = "/.claude/worktrees/"


def _owner_env(config_owner: Optional[str]) -> str:
    return f"{CONFIG_OWNER_ENV_VAR}={config_owner}" if config_owner else ""


def evaluate_hook_command(
    harness_id: str, verb: str, *, config_owner: Optional[str]
) -> str:
    """The standard ``yoke hook evaluate`` command for one harness."""
    parts = [
        f'{ROOT_VARIABLE}="{HOOK_ROOT_EXPRESSIONS[harness_id]}"',
        _IDENTITY_ENV[harness_id],
        _owner_env(config_owner),
        f"{YOKE_HOOK_EVALUATE} {verb}",
    ]
    return hook_shell_command("env " + " ".join(part for part in parts if part))


def cwd_resilient_hook_command(verb: str, *, config_owner: str) -> str:
    """Cursor command that still runs when its project folder is gone.

    Cursor spawns a project hook with cwd = project root, so a deleted linked
    worktree would skip it. This body picks an existing ``YOKE_ROOT``
    (peeling a missing ``.worktrees/<lane>`` to its parent checkout) and
    ``cd``s there before evaluating. It uses ``case`` arms and ``if`` blocks
    instead of ``|`` and keeps globs in variables, so no ``|``, ``/*`` or
    ``*/`` reaches the rendered file.
    """
    body = (
        f'wt="{_WORKTREE_SEGMENT}"; cwt="{_CLAUDE_WORKTREE_SEGMENT}"; '
        'root=""; '
        'for c in "$YOKE_ROOT" "$CURSOR_PROJECT_DIR" "$PWD"; do '
        '[ -n "$c" ] && [ -d "$c" ] && root="$c" && break; '
        "done; "
        'if [ -z "$root" ]; then '
        'for c in "$CURSOR_PROJECT_DIR" "$YOKE_ROOT"; do '
        'case "$c" in '
        '*"$wt"*) p="${c%%$wt*}"; '
        'p="${p%%$cwt*}"; '
        '[ -d "$p" ] && root="$p" && break;; '
        '*"$cwt"*) p="${c%%$cwt*}"; '
        '[ -d "$p" ] && root="$p" && break;; '
        "esac; "
        "done; "
        "fi; "
        'if [ -z "$root" ]; then root="${HOME:-/tmp}"; fi; '
        'if ! cd "$root" 2>/dev/null; then '
        'if ! cd "${HOME:-/tmp}" 2>/dev/null; then cd /; fi; '
        "fi; "
        f'env {ROOT_VARIABLE}="$root" {_IDENTITY_ENV["cursor"]} '
        f"{_owner_env(config_owner)} {YOKE_HOOK_EVALUATE} {verb}"
    )
    return hook_shell_command(body)


def _user_command(spec: HarnessMachineHooks, event: MachineHookEvent) -> str:
    if spec.harness_id == "cursor":
        # User hooks spawn from ~/.cursor, so every event resolves its root.
        return cwd_resilient_hook_command(event.verb, config_owner=spec.config_owner)
    return evaluate_hook_command(
        spec.harness_id, event.verb, config_owner=spec.config_owner
    )


def _user_entry(spec: HarnessMachineHooks, event: MachineHookEvent) -> dict[str, Any]:
    command = _user_command(spec, event)
    if spec.harness_id == "cursor":
        return {"command": command, "timeout": CURSOR_HOOK_TIMEOUT_S}
    entry: dict[str, Any] = {}
    if event.matcher is not None:
        entry["matcher"] = event.matcher
    entry["hooks"] = [{"type": "command", "command": command}]
    return entry


def render_user_hook_entries(spec: HarnessMachineHooks) -> dict[str, list[dict]]:
    """Native event -> the Yoke entries the user config must hold."""
    rendered: dict[str, list[dict]] = {}
    for event in spec.events:
        rendered.setdefault(event.native_event, []).append(_user_entry(spec, event))
    return rendered


def is_machine_hook_entry(entry: object, spec: HarnessMachineHooks) -> bool:
    """True for an entry Yoke wrote into this harness's user config."""
    marker = _owner_env(spec.config_owner)
    return any(
        marker in command or any(retired in command for retired in RETIRED_USER_HOOK_MARKERS)
        for command in entry_commands(entry)
    )


__all__ = [
    "CURSOR_HOOK_TIMEOUT_S",
    "HOOK_ROOT_EXPRESSIONS",
    "ROOT_VARIABLE",
    "YOKE_HOOK_EVALUATE",
    "cwd_resilient_hook_command",
    "evaluate_hook_command",
    "is_machine_hook_entry",
    "render_user_hook_entries",
]
