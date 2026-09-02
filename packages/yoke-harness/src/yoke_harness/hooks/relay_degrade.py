"""Fail-open rendering for a hook relay that could not reach the server.

Transport failure must never block the tool call the hook was guarding, so
the relay degrades to a local-only allow. Cursor is the one surface that
needs to be TOLD: its context-carrying events render JSON, so the warning
rides in that payload where the operator reads it rather than into a
stderr stream the client does not surface.
"""

from __future__ import annotations

import json
import sys

from yoke_contracts.hook_runner.chain_registry import SESSION_START_EVENT
from yoke_contracts.hook_runner.cursor_response import cursor_lifecycle_allow_stdout

from yoke_harness.hooks.identity import detect_executor, is_cursor
from yoke_harness.hooks.relay_identity_guard import print_execution_provenance


DEGRADED_MARKER = "YOKE_HOOK_DEGRADED"
_CURSOR_CONTEXT_EVENTS = frozenset({SESSION_START_EVENT, "PostToolUse"})


def _cursor_degradation_stdout(
    event_name: str, detail: str, preserved_stdout: str
) -> str:
    if not is_cursor(detect_executor()):
        return preserved_stdout
    preserved_stdout = cursor_lifecycle_allow_stdout(event_name, preserved_stdout)
    if event_name not in _CURSOR_CONTEXT_EVENTS:
        return preserved_stdout
    warning = (
        "WARNING: Yoke hook relay degraded to local-only allow; "
        f"server policy was not evaluated ({detail})"
    )
    try:
        payload = json.loads(preserved_stdout) if preserved_stdout else {}
    except (json.JSONDecodeError, TypeError):
        payload = {}
    if isinstance(payload, dict) and isinstance(payload.get("additional_context"), str):
        payload["additional_context"] += "\n\n" + warning
        return json.dumps(payload)
    return json.dumps({"additional_context": warning})


def degrade_to_noop(event_name: str, detail: str, *, preserved_stdout: str = "") -> int:
    """Fail open for hook transport/local harness failures."""
    sys.stderr.write(
        f"WARNING: {DEGRADED_MARKER}: yoke hook evaluate {event_name}: "
        "https transport degraded "
        f"to no-op allow ({detail})\n"
    )
    print_execution_provenance(fallback_local=True)
    visible_stdout = _cursor_degradation_stdout(
        event_name,
        detail,
        preserved_stdout,
    )
    if visible_stdout:
        sys.stdout.write(visible_stdout)
    return 0


__all__ = ["DEGRADED_MARKER", "degrade_to_noop"]
