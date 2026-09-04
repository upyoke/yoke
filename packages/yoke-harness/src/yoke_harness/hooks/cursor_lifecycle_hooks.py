"""Cursor stop/sessionEnd commands that survive a deleted project root.

Cursor project hooks spawn with cwd = project root. When that directory is
gone (common after remounting onto a linked worktree that was later
removed), the OS refuses the spawn and ``yoke hook evaluate Stop`` never
runs. User hooks spawn from ``~/.cursor`` and still fire — so Yoke keeps a
machine-local stop/sessionEnd backstop there, and both command shapes
resolve ``YOKE_ROOT`` to a directory that exists before evaluating.

These two command bodies also stay clear of the byte sequences Cursor's
JSONC hook loader mishandles; see
:data:`yoke_contracts.cursor_hook_command_bytes.CURSOR_HOOK_COMMAND_BYTE_REASON`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from yoke_contracts.hook_runner.config_owner import (
    CONFIG_OWNER_ENV_VAR,
    CURSOR_LIFECYCLE_COMMAND_MARKER,
    CURSOR_LIFECYCLE_COMMAND_MARKERS,
    CURSOR_PROJECT_CONFIG_OWNER,
    CURSOR_USER_LIFECYCLE_OWNER,
)
from yoke_harness.hooks.shell_command import hook_shell_command

_YOKE_HOOK_EVALUATE = "yoke hook evaluate"
_CURSOR_IDENTITY_ENV = "YOKE_EXECUTOR=cursor"

# Cursor-native event names that must survive a missing project cwd.
USER_LIFECYCLE_EVENTS: tuple[str, str] = ("stop", "sessionEnd")

# Runner verbs paired with the Cursor-native names above.
_LIFECYCLE_VERBS: dict[str, str] = {
    "stop": "Stop",
    "sessionEnd": "SessionEnd",
}

# Why these bodies avoid ``|``, ``/*`` and ``*/`` entirely.
#
# Bisected 2026-09-04 on cursor-agent 2026.09.02-c22c1a3 with scratch
# projects and file-writing capture hooks. Two independent silent failures
# were reproduced there, both costing every tool hook:
#
# * a vertical bar in BOTH the ``stop`` and ``sessionEnd`` commands stops
#   beforeShellExecution, afterShellExecution, preToolUse and postToolUse
#   spawning, while sessionStart and stop still fire, so the file is plainly
#   loaded; padding the file back to the same byte size does not restore
#   them, so length is not the trigger;
# * ``/*`` anywhere in a command opens a JSONC comment that runs to the next
#   ``*/`` across JSON string boundaries, deleting every hook entry between
#   them — a ``sessionEnd`` command carrying ``*/.worktrees/*`` and a later
#   ``stop`` command carrying ``*/`` swallowed all the tool hooks between.
#
# Either way relay Cursor launches never fired a tool hook, never wrote the
# conversation map, never registered, and died on the 10-minute registration
# deadline. So the rewrite covers the whole byte class rather than one
# instance of it: mutually exclusive ``case`` arms replace the pattern
# alternation, ``if`` blocks replace every ``||`` fallback chain, and the
# worktree path segments live in variables so no glob in this body ever
# spells ``/*`` or ``*/`` in the rendered file.
#
# The worktree path segments the fallback peels. Held in variables, and
# expanded unquoted into ``case`` patterns and ``${...%%}`` words, so the
# rendered command text never carries a JSONC comment delimiter.
_WORKTREE_SEGMENT = "/.worktrees/"
_CLAUDE_WORKTREE_SEGMENT = "/.claude/worktrees/"


def cursor_lifecycle_hook_command(
    event_verb: str,
    *,
    config_owner: str = CURSOR_PROJECT_CONFIG_OWNER,
) -> str:
    """Shell command for Cursor ``stop`` / ``sessionEnd`` (and user backstop).

    Picks an existing ``YOKE_ROOT`` (peeling a missing ``.worktrees/<lane>``
    to its parent checkout) and ``cd``s there when possible before
    ``yoke hook evaluate``. Pair with Cursor decision rendering that emits
    ``{}`` on these events so the vendor stop contract stays satisfied.
    """
    # The shared wrapper rejects single quotes in this trusted shell body.
    # No ``|``, ``/*`` or ``*/`` anywhere in it either: see
    # yoke_contracts.cursor_hook_command_bytes.
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
        f'env YOKE_ROOT="$root" {_CURSOR_IDENTITY_ENV} '
        f"{CURSOR_LIFECYCLE_COMMAND_MARKER} "
        f"{CONFIG_OWNER_ENV_VAR}={config_owner} "
        f"{_YOKE_HOOK_EVALUATE} {event_verb}"
    )
    return hook_shell_command(body)


def _lifecycle_entry(event_verb: str) -> dict[str, Any]:
    return {
        "command": cursor_lifecycle_hook_command(
            event_verb,
            config_owner=CURSOR_USER_LIFECYCLE_OWNER,
        ),
        "timeout": 30,
    }


def _is_yoke_lifecycle_entry(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    command = entry.get("command")
    return isinstance(command, str) and any(
        marker in command for marker in CURSOR_LIFECYCLE_COMMAND_MARKERS
    )


def ensure_user_lifecycle_hooks(
    *,
    hooks_path: Optional[Path] = None,
) -> bool:
    """Merge Yoke stop/sessionEnd into ``~/.cursor/hooks.json``.

    Returns True when the file was written. Idempotent: replaces prior Yoke
    lifecycle entries (identified by the shell marker) and leaves unrelated
    operator hooks alone. Best-effort — never raises into the hook path.
    """
    try:
        path = hooks_path or (Path.home() / ".cursor" / "hooks.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeError):
                loaded = {}
            if isinstance(loaded, dict):
                payload = loaded
        hooks = payload.get("hooks")
        if not isinstance(hooks, dict):
            hooks = {}
        for native_event, verb in _LIFECYCLE_VERBS.items():
            existing = hooks.get(native_event)
            if not isinstance(existing, list):
                existing = []
            kept = [
                e
                for e in existing
                if not _is_yoke_lifecycle_entry(e)
                and not (
                    isinstance(e, dict)
                    and isinstance(e.get("command"), str)
                    and "yoke-cursor-stop-canary" in e["command"]
                )
            ]
            hooks[native_event] = [_lifecycle_entry(verb), *kept]
        payload["version"] = int(payload.get("version") or 1)
        payload["hooks"] = hooks
        new_text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        old_text = path.read_text(encoding="utf-8") if path.is_file() else ""
        if new_text == old_text:
            return False
        path.write_text(new_text, encoding="utf-8")
        return True
    except Exception:  # noqa: BLE001 — hook transport must stay open
        return False


def ensure_user_lifecycle_hooks_for_executor(executor: str) -> None:
    """No-op unless *executor* is a Cursor family id."""
    from yoke_harness.hooks.identity import is_cursor

    if not is_cursor(executor):
        return
    ensure_user_lifecycle_hooks()


__all__ = [
    "USER_LIFECYCLE_EVENTS",
    "cursor_lifecycle_hook_command",
    "ensure_user_lifecycle_hooks",
    "ensure_user_lifecycle_hooks_for_executor",
]
