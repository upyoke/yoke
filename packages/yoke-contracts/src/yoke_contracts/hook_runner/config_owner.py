"""Ownership marker for hook configs imported across harnesses."""

from __future__ import annotations

from collections.abc import Mapping


CONFIG_OWNER_ENV_VAR = "YOKE_HOOK_CONFIG_OWNER"
CLAUDE_CONFIG_OWNER = "claude"
CURSOR_PROCESS_ENV_VARS = (
    "CURSOR_PROJECT_DIR",
    "CURSOR_TRANSCRIPT_PATH",
    "CURSOR_INVOKED_AS",
)


def is_cursor_imported_claude_hook(environment: Mapping[str, str]) -> bool:
    """True when Cursor is invoking a hook owned by Claude project config."""
    return (
        environment.get(CONFIG_OWNER_ENV_VAR) == CLAUDE_CONFIG_OWNER
        and any(environment.get(key) for key in CURSOR_PROCESS_ENV_VARS)
    )


__all__ = [
    "CLAUDE_CONFIG_OWNER",
    "CONFIG_OWNER_ENV_VAR",
    "CURSOR_PROCESS_ENV_VARS",
    "is_cursor_imported_claude_hook",
]
