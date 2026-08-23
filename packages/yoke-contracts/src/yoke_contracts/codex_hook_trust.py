"""Pure Codex hook normalization and trust comparison.

Codex persists one ``trusted_hash`` per normalized hook handler.  The hash is
not the hooks file's byte digest: it covers the event, effective matcher, and
one normalized handler.  Keep this client-safe helper shared by the engine and
CLI inventory readers so both report the same approval state.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from typing import Any, Dict, Optional


_EVENTS = (
    ("PreToolUse", "pre_tool_use"),
    ("PermissionRequest", "permission_request"),
    ("PostToolUse", "post_tool_use"),
    ("PreCompact", "pre_compact"),
    ("PostCompact", "post_compact"),
    ("SessionStart", "session_start"),
    ("SessionEnd", "session_end"),
    ("UserPromptSubmit", "user_prompt_submit"),
    ("SubagentStart", "subagent_start"),
    ("SubagentStop", "subagent_stop"),
    ("Stop", "stop"),
)
_MATCHER_EVENTS = {
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "PreCompact",
    "PostCompact",
    "SessionStart",
    "SessionEnd",
    "SubagentStart",
    "SubagentStop",
}
_CONTEXT_LIMIT_EVENTS = {
    "PreToolUse",
    "PostToolUse",
    "SessionStart",
    "UserPromptSubmit",
    "SubagentStart",
}
_DEFAULT_CONTEXT_LIMIT = 2_500


class _MalformedHooks(ValueError):
    pass


def _optional_string(value: Any, name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _MalformedHooks(f"{name} must be a string")
    return value


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _MalformedHooks(f"{name} must be a non-negative integer")
    return value


def _normalized_command(event: str, handler: Mapping[str, Any]) -> Dict[str, Any]:
    command = handler.get("command")
    if not isinstance(command, str) or not command.strip():
        raise _MalformedHooks("command hook requires a non-empty command")
    windows_keys = {"commandWindows", "command_windows"} & set(handler)
    if len(windows_keys) > 1:
        raise _MalformedHooks("commandWindows is duplicated")
    windows_command = _optional_string(
        handler.get(next(iter(windows_keys))) if windows_keys else None,
        "commandWindows",
    )
    if os.name == "nt" and windows_command is not None:
        command = windows_command
    timeout = handler.get("timeout")
    if timeout is None:
        timeout = 1 if event == "SessionEnd" else 600
    else:
        timeout = max(1, _integer(timeout, "timeout"))
        if event == "SessionEnd":
            timeout = min(3, timeout)
    runs_async = handler.get("async", False)
    if not isinstance(runs_async, bool):
        raise _MalformedHooks("async must be a boolean")
    normalized: Dict[str, Any] = {
        "type": "command",
        "command": command,
        "timeout": timeout,
        "async": runs_async,
    }
    status_message = _optional_string(handler.get("statusMessage"), "statusMessage")
    if status_message is not None:
        normalized["statusMessage"] = status_message
    limit = handler.get("additionalContextLimit")
    if limit is not None:
        limit = _integer(limit, "additionalContextLimit")
        if event in _CONTEXT_LIMIT_EVENTS and limit != _DEFAULT_CONTEXT_LIMIT:
            normalized["additionalContextLimit"] = limit
    return normalized


def _toml_representable(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, bool, int, float)):
        return True
    if isinstance(value, list):
        return all(_toml_representable(item) for item in value)
    if isinstance(value, Mapping):
        return all(
            isinstance(key, str) and _toml_representable(item)
            for key, item in value.items()
        )
    return False


def _normalized_mcp(event: str, handler: Mapping[str, Any]) -> Dict[str, Any]:
    if event == "SessionEnd":
        raise _MalformedHooks("SessionEnd does not support MCP hooks")
    server = handler.get("server")
    tool = handler.get("tool")
    if not isinstance(server, str) or not server.strip():
        raise _MalformedHooks("MCP hook requires a server")
    if not isinstance(tool, str) or not tool.strip():
        raise _MalformedHooks("MCP hook requires a tool")
    hook_input = handler.get("input", {})
    if not isinstance(hook_input, Mapping) or not _toml_representable(hook_input):
        raise _MalformedHooks("MCP input must be TOML-representable")
    timeout = handler.get("timeout")
    timeout = 600 if timeout is None else max(1, _integer(timeout, "timeout"))
    normalized: Dict[str, Any] = {
        "type": "mcp_tool",
        "server": server,
        "tool": tool,
        "input": dict(hook_input),
        "timeout": timeout,
    }
    status_message = _optional_string(handler.get("statusMessage"), "statusMessage")
    if status_message is not None:
        normalized["statusMessage"] = status_message
    return normalized


def _handler(event: str, handler: Any) -> Dict[str, Any]:
    if not isinstance(handler, Mapping):
        raise _MalformedHooks("hook handler must be an object")
    kind = handler.get("type")
    if kind == "command":
        return _normalized_command(event, handler)
    if kind == "mcp_tool":
        return _normalized_mcp(event, handler)
    raise _MalformedHooks("hook handler type is unsupported")


def _digest(identity: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        identity,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def normalized_codex_hook_hashes(payload: Any) -> Optional[Dict[str, str]]:
    """Return ``event:group:handler -> hash``, or ``None`` when malformed."""
    try:
        if not isinstance(payload, Mapping) or set(payload) - {"description", "hooks"}:
            raise _MalformedHooks("hooks file must be an object")
        _optional_string(payload.get("description"), "description")
        hooks = payload.get("hooks")
        if not isinstance(hooks, Mapping):
            raise _MalformedHooks("hooks must be an object")
        hashes: Dict[str, str] = {}
        for event, label in _EVENTS:
            groups = hooks.get(event, [])
            if not isinstance(groups, list):
                raise _MalformedHooks(f"{event} must be a list")
            for group_index, group in enumerate(groups):
                if not isinstance(group, Mapping):
                    raise _MalformedHooks("matcher group must be an object")
                matcher = _optional_string(group.get("matcher"), "matcher")
                if event not in _MATCHER_EVENTS:
                    matcher = None
                handlers = group.get("hooks", [])
                if not isinstance(handlers, list):
                    raise _MalformedHooks("group hooks must be a list")
                for handler_index, raw_handler in enumerate(handlers):
                    identity: Dict[str, Any] = {
                        "event_name": label,
                        "hooks": [_handler(event, raw_handler)],
                    }
                    if matcher is not None:
                        identity["matcher"] = matcher
                    suffix = f"{label}:{group_index}:{handler_index}"
                    hashes[suffix] = _digest(identity)
        return hashes
    except (_MalformedHooks, TypeError, ValueError):
        return None


def codex_hooks_are_approved(payload: Any, trusted: Mapping[str, str]) -> bool:
    """True only when current handlers exactly match literal-path trust entries."""
    current = normalized_codex_hook_hashes(payload)
    return bool(current) and current == dict(trusted)


__all__ = ["codex_hooks_are_approved", "normalized_codex_hook_hashes"]
