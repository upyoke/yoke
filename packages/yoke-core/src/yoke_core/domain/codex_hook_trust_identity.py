"""Compute the normalized hook identities persisted by Codex trust state."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


_EVENT_LABELS = {
    "PreToolUse": "pre_tool_use",
    "PermissionRequest": "permission_request",
    "PostToolUse": "post_tool_use",
    "PreCompact": "pre_compact",
    "PostCompact": "post_compact",
    "SessionStart": "session_start",
    "SessionEnd": "session_end",
    "UserPromptSubmit": "user_prompt_submit",
    "SubagentStart": "subagent_start",
    "SubagentStop": "subagent_stop",
    "Stop": "stop",
}
_MATCHER_EVENTS = frozenset(_EVENT_LABELS) - {"UserPromptSubmit", "Stop"}
_CONTEXT_EVENTS = frozenset(
    {"PreToolUse", "PostToolUse", "SessionStart", "UserPromptSubmit", "SubagentStart"}
)
_DEFAULT_TIMEOUT_SEC = 600
_SESSION_END_DEFAULT_TIMEOUT_SEC = 1
_SESSION_END_MAX_TIMEOUT_SEC = 3
_DEFAULT_CONTEXT_LIMIT = 2_500


class CodexHookIdentityError(ValueError):
    """The hooks document cannot produce Codex-compatible trust identities."""


def codex_hook_hashes(hooks_path: Path) -> Dict[str, str]:
    """Return ``event:group:handler -> sha256`` for discovered handlers.

    Codex hashes one normalized identity per handler. Its identity includes the
    event and matcher group, the one selected handler, and runtime defaults
    such as the command timeout and synchronous execution flag.
    """
    try:
        document = json.loads(hooks_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CodexHookIdentityError(str(exc)) from exc
    return codex_hook_hashes_from_document(document)


def codex_hook_hashes_from_document(document: object) -> Dict[str, str]:
    """Compute Codex hook hashes from an already-decoded hooks document."""
    root = _mapping(document, "hooks document")
    unknown = set(root) - {"description", "hooks"}
    if unknown:
        raise CodexHookIdentityError(f"unknown top-level keys: {sorted(unknown)}")
    events = _mapping(root.get("hooks", {}), "hooks")
    hashes: Dict[str, str] = {}
    for event_name, label in _EVENT_LABELS.items():
        groups = _list(events.get(event_name, []), event_name)
        for group_index, raw_group in enumerate(groups):
            group = _mapping(raw_group, f"{event_name}[{group_index}]")
            matcher = _optional_string(group.get("matcher"), "matcher")
            handlers = _list(group.get("hooks", []), "hooks")
            for handler_index, raw_handler in enumerate(handlers):
                handler = _normalized_handler(event_name, raw_handler)
                if handler is None:
                    continue
                identity: Dict[str, Any] = {
                    "event_name": label,
                    "hooks": [handler],
                }
                if event_name in _MATCHER_EVENTS and matcher is not None:
                    identity["matcher"] = matcher
                suffix = f"{label}:{group_index}:{handler_index}"
                hashes[suffix] = _canonical_hash(identity)
    return hashes


def _normalized_handler(
    event_name: str, raw_handler: object
) -> Optional[Dict[str, Any]]:
    handler = _mapping(raw_handler, "hook handler")
    handler_type = handler.get("type")
    if handler_type == "command":
        command = _platform_command(handler)
        if not command.strip():
            return None
        normalized: Dict[str, Any] = {
            "type": "command",
            "command": command,
            "timeout": _command_timeout(event_name, handler.get("timeout")),
            "async": _boolean(handler.get("async", False), "async"),
        }
        status_message = _optional_string(handler.get("statusMessage"), "statusMessage")
        if status_message is not None:
            normalized["statusMessage"] = status_message
        context_limit = _optional_uint(
            handler.get("additionalContextLimit"), "additionalContextLimit"
        )
        if (
            event_name in _CONTEXT_EVENTS
            and context_limit is not None
            and context_limit != _DEFAULT_CONTEXT_LIMIT
        ):
            normalized["additionalContextLimit"] = context_limit
        return normalized
    if handler_type == "mcp_tool":
        if event_name == "SessionEnd":
            return None
        server = _string(handler.get("server"), "server")
        tool = _string(handler.get("tool"), "tool")
        if not server.strip() or not tool.strip():
            return None
        timeout = _optional_uint(handler.get("timeout"), "timeout")
        normalized = {
            "type": "mcp_tool",
            "server": server,
            "tool": tool,
            "input": _mapping(handler.get("input", {}), "input"),
            "timeout": max(1, _DEFAULT_TIMEOUT_SEC if timeout is None else timeout),
        }
        status_message = _optional_string(handler.get("statusMessage"), "statusMessage")
        if status_message is not None:
            normalized["statusMessage"] = status_message
        return normalized
    if handler_type in {"prompt", "agent"}:
        return None
    raise CodexHookIdentityError(f"unsupported hook handler type: {handler_type!r}")


def _platform_command(handler: Dict[str, Any]) -> str:
    command = _string(handler.get("command"), "command")
    windows_value = handler.get("commandWindows", handler.get("command_windows"))
    command_windows = _optional_string(windows_value, "commandWindows")
    if os.name == "nt" and command_windows is not None:
        return command_windows
    return command


def _command_timeout(event_name: str, value: object) -> int:
    timeout = _optional_uint(value, "timeout")
    if event_name == "SessionEnd":
        selected = _SESSION_END_DEFAULT_TIMEOUT_SEC if timeout is None else timeout
        return min(_SESSION_END_MAX_TIMEOUT_SEC, max(1, selected))
    return max(1, _DEFAULT_TIMEOUT_SEC if timeout is None else timeout)


def _canonical_hash(identity: Dict[str, Any]) -> str:
    encoded = json.dumps(
        identity,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _mapping(value: object, label: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise CodexHookIdentityError(f"{label} must be an object")
    return value


def _list(value: object, label: str) -> list:
    if not isinstance(value, list):
        raise CodexHookIdentityError(f"{label} must be an array")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise CodexHookIdentityError(f"{label} must be a string")
    return value


def _optional_string(value: object, label: str) -> Optional[str]:
    if value is None:
        return None
    return _string(value, label)


def _optional_uint(value: object, label: str) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CodexHookIdentityError(f"{label} must be an unsigned integer")
    return value


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise CodexHookIdentityError(f"{label} must be a boolean")
    return value


__all__ = [
    "CodexHookIdentityError",
    "codex_hook_hashes",
    "codex_hook_hashes_from_document",
]
