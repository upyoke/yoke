"""Canonical routing rules for resident hook evaluation."""

from __future__ import annotations

import json
from typing import Any, Mapping

from yoke_contracts.hook_runner.hook_ordering import ordered_pipeline_for


_TOOL_EVENTS = frozenset(
    {"PreToolUse", "PostToolUse", "PostToolUseFailure"}
)

# These chain members produce delivery, liveness, or telemetry side effects,
# but never decide whether a tool may run. The server batch endpoint preserves
# their durable effects for locally evaluated read-only hooks.
_ASYNC_SAFE_MODULES = frozenset(
    {
        "yoke_core.hooks.session_message_delivery",
        "yoke_core.hooks.session_launch_attestation",
        "yoke_core.hooks.session_broker_wake",
        "yoke_core.hooks.heartbeat",
        "yoke_core.domain.observe_pre",
        "yoke_core.domain.observe",
    }
)


def parse_hook_payload(stdin_data: str) -> dict[str, Any]:
    try:
        payload = json.loads(stdin_data) if stdin_data else {}
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _tool_name(payload: Mapping[str, Any]) -> str:
    value = payload.get("tool_name")
    return value if isinstance(value, str) else ""


def _chain_is_async_safe(event_name: str, tool_name: str) -> bool:
    chain = ordered_pipeline_for(event_name, tool_name or "_default")
    return bool(chain) and all(module in _ASYNC_SAFE_MODULES for module in chain)


def is_read_only_tool_event(event_name: str, stdin_data: str) -> bool:
    """Return whether this tool event has no synchronous policy decision.

    The pre-tool chain is consulted even for post events, so a guarded tool
    such as Write remains on the relayed path for its entire call. Unknown
    tools follow the registry's ``_default`` chain instead of a second list
    that could drift from rendered harness policy.
    """
    if event_name not in _TOOL_EVENTS:
        return False
    payload = parse_hook_payload(stdin_data)
    tool_name = _tool_name(payload)
    if not tool_name:
        return False
    return _chain_is_async_safe(
        "PreToolUse", tool_name
    ) and _chain_is_async_safe(event_name, tool_name)


def message_probe_key(stdin_data: str) -> str:
    payload = parse_hook_payload(stdin_data)
    value = payload.get("session_id")
    return value.strip() if isinstance(value, str) else ""


__all__ = [
    "is_read_only_tool_event",
    "message_probe_key",
    "parse_hook_payload",
]
