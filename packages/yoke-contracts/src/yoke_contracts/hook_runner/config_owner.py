"""Ownership marker for hook configs imported across harnesses."""

from __future__ import annotations

from collections.abc import Mapping


CONFIG_OWNER_ENV_VAR = "YOKE_HOOK_CONFIG_OWNER"
EXECUTOR_ENV_VAR = "YOKE_EXECUTOR"
CURSOR_EXECUTOR_ID = "cursor"
CLAUDE_CONFIG_OWNER = "claude"
CURSOR_PROJECT_CONFIG_OWNER = "cursor-project"
CURSOR_USER_LIFECYCLE_OWNER = "cursor-user-lifecycle"
CURSOR_LIFECYCLE_COMMAND_MARKER = "yoke-cursor-lifecycle-root=1"
CURSOR_PROCESS_ENV_VARS = (
    "CURSOR_PROJECT_DIR",
    "CURSOR_TRANSCRIPT_PATH",
    "CURSOR_INVOKED_AS",
)
CURSOR_NATIVE_RUNNER_EVENTS: tuple[tuple[str, str], ...] = (
    ("sessionStart", "SessionStart"),
    ("sessionEnd", "SessionEnd"),
    ("beforeSubmitPrompt", "UserPromptSubmit"),
    ("beforeShellExecution", "PreToolUse"),
    ("afterShellExecution", "PostToolUse"),
    ("preToolUse", "PreToolUse"),
    ("postToolUse", "PostToolUse"),
    ("postToolUseFailure", "PostToolUseFailure"),
    ("stop", "Stop"),
)
CURSOR_COMPATIBILITY_RUNNER_ALIASES = {"PermissionRequest": "PreToolUse"}


def is_cursor_hook_payload(
    environment: Mapping[str, str], payload: Mapping[str, object],
) -> bool:
    """True when process and payload provenance both identify Cursor."""
    session_id = payload.get("session_id")
    conversation_id = payload.get("conversation_id")
    return (
        any(environment.get(key) for key in CURSOR_PROCESS_ENV_VARS)
        and isinstance(session_id, str)
        and bool(session_id)
        and session_id == conversation_id
    )


def is_cursor_imported_claude_hook(
    environment: Mapping[str, str], payload: Mapping[str, object],
) -> bool:
    """True when Cursor is invoking a hook owned by Claude project config."""
    return (
        environment.get(CONFIG_OWNER_ENV_VAR) == CLAUDE_CONFIG_OWNER
        and is_cursor_hook_payload(environment, payload)
    )


__all__ = [
    "CLAUDE_CONFIG_OWNER",
    "CONFIG_OWNER_ENV_VAR",
    "CURSOR_COMPATIBILITY_RUNNER_ALIASES",
    "CURSOR_EXECUTOR_ID",
    "CURSOR_LIFECYCLE_COMMAND_MARKER",
    "CURSOR_NATIVE_RUNNER_EVENTS",
    "CURSOR_PROJECT_CONFIG_OWNER",
    "CURSOR_PROCESS_ENV_VARS",
    "CURSOR_USER_LIFECYCLE_OWNER",
    "EXECUTOR_ENV_VAR",
    "is_cursor_imported_claude_hook",
    "is_cursor_hook_payload",
]
