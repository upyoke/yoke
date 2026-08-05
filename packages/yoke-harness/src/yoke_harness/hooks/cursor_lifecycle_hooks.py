"""Cursor stop/sessionEnd commands that survive a deleted project root.

Cursor project hooks spawn with cwd = project root. When that directory is
gone (common after remounting onto a linked worktree that was later
removed), the OS refuses the spawn and ``yoke hook evaluate Stop`` never
runs. User hooks spawn from ``~/.cursor`` and still fire — so Yoke keeps a
machine-local stop/sessionEnd backstop there, and both command shapes
resolve ``YOKE_ROOT`` to a directory that exists before evaluating.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

_YOKE_HOOK_EVALUATE = "yoke hook evaluate"
_CURSOR_IDENTITY_ENV = "YOKE_EXECUTOR=cursor"

# Cursor-native event names that must survive a missing project cwd.
USER_LIFECYCLE_EVENTS: tuple[str, str] = ("stop", "sessionEnd")

# Runner verbs paired with the Cursor-native names above.
_LIFECYCLE_VERBS: dict[str, str] = {
    "stop": "Stop",
    "sessionEnd": "SessionEnd",
}

_MARKER = "yoke-cursor-lifecycle-root"


def cursor_lifecycle_hook_command(event_verb: str) -> str:
    """Shell command for Cursor ``stop`` / ``sessionEnd`` (and user backstop).

    Picks an existing ``YOKE_ROOT`` (peeling a missing ``.worktrees/<lane>``
    to its parent checkout) and ``cd``s there when possible before
    ``yoke hook evaluate``. Pair with Cursor decision rendering that emits
    ``{}`` on these events so the vendor stop contract stays satisfied.
    """
    # Single-quoted -lc body: no single quotes inside.
    body = (
        f'{_MARKER}=1; '
        'root=""; '
        'for c in "$YOKE_ROOT" "$CURSOR_PROJECT_DIR" "$PWD"; do '
        '[ -n "$c" ] && [ -d "$c" ] && root="$c" && break; '
        'done; '
        'if [ -z "$root" ]; then '
        'for c in "$CURSOR_PROJECT_DIR" "$YOKE_ROOT"; do '
        'case "$c" in '
        '*/.worktrees/*|*/.claude/worktrees/*) '
        'p="${c%%/.worktrees/*}"; '
        'p="${p%%/.claude/worktrees/*}"; '
        '[ -d "$p" ] && root="$p" && break;; '
        'esac; '
        'done; '
        'fi; '
        '[ -n "$root" ] || root="${HOME:-/tmp}"; '
        'cd "$root" 2>/dev/null || cd "${HOME:-/tmp}" 2>/dev/null || cd /; '
        f'env YOKE_ROOT="$root" {_CURSOR_IDENTITY_ENV} '
        f'{_YOKE_HOOK_EVALUATE} {event_verb}'
    )
    return f"/bin/zsh -lc '{body}'"


def _lifecycle_entry(event_verb: str) -> dict[str, Any]:
    return {
        "command": cursor_lifecycle_hook_command(event_verb),
        "timeout": 30,
    }


def _is_yoke_lifecycle_entry(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    command = entry.get("command")
    return isinstance(command, str) and _MARKER in command


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
                e for e in existing
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
