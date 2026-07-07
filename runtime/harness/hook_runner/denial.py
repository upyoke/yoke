"""Denial event payload construction + emission for PreToolUse guards.

Builds the ``HarnessToolCallDenied`` context payload from a hook /
check / reason tuple and pushes it through the native
``yoke_core.domain.events.emit_event`` CLI. Imported by lint guards
that need only the denial path; ``runtime.harness.hook_runner.telemetry``
re-exports the public surface so call sites can ``mock.patch`` against
``runtime.harness.hook_runner.telemetry.emit_denial_event``.
"""

from __future__ import annotations

import json
from typing import Any


COMMAND_SNIPPET_MAX_BYTES = 512


def build_denial_payload(
    hook: str = "",
    check_id: str = "",
    reason: str = "",
    command_snippet: str = "",
) -> dict[str, Any]:
    """Build the context payload for a HarnessToolCallDenied event."""
    payload = {
        "hook": hook,
        "check_id": check_id,
        "reason": reason.replace("\n", " ")[:500],
    }
    if command_snippet:
        payload["command_snippet"] = command_snippet.replace("\n", " ")[
            :COMMAND_SNIPPET_MAX_BYTES
        ]
    return payload


def build_denial_context(
    hook: str = "",
    check_id: str = "",
    reason: str = "",
    command_snippet: str = "",
) -> str:
    """Build the compact JSON context for a HarnessToolCallDenied event."""
    return json.dumps(
        build_denial_payload(
            hook=hook,
            check_id=check_id,
            reason=reason,
            command_snippet=command_snippet,
        ),
        separators=(",", ":"),
    )


def emit_denial_event(
    hook: str = "",
    tool: str = "",
    check_id: str = "",
    reason: str = "",
    session_id: str = "",
    tool_use_id: str = "",
    turn_id: str = "",
    command_snippet: str = "",
    outcome: str = "denied",
) -> None:
    """Emit HarnessToolCallDenied via the Python emit-event owner.

    ``outcome`` defaults to ``"denied"`` so existing callers keep the
    legacy event shape. Lint hooks may pass ``"suppression_attempted"``
    to distinguish suppression-token paths from ordinary denials in the
    audit stream — see
    ``runtime/api/domain/lint_long_command_polling_decide.py``.
    """
    payload = build_denial_payload(
        hook=hook,
        check_id=check_id,
        reason=reason,
        command_snippet=command_snippet,
    )
    if tool_use_id:
        payload["tool_use_id"] = tool_use_id
    if turn_id:
        payload["turn_id"] = turn_id
    try:
        from yoke_core.domain import emit_event as emit_event_cli

        parser = emit_event_cli.build_parser()
        args = parser.parse_args(
            [
                "--name",
                "HarnessToolCallDenied",
                "--kind",
                "audit",
                "--type",
                "tool_call",
                "--source-type",
                "hook",
                "--severity",
                "WARN",
                "--outcome",
                outcome or "denied",
                "--tool-name",
                tool or "",
                "--hook-event-name",
                "PreToolUse",
                "--context",
                json.dumps(payload, separators=(",", ":")),
                *(["--session-id", session_id] if session_id else []),
                *(["--tool-use-id", tool_use_id] if tool_use_id else []),
                *(["--turn-id", turn_id] if turn_id else []),
            ]
        )
        emit_event_cli.emit(args)
    except Exception:
        pass


__all__ = [
    "COMMAND_SNIPPET_MAX_BYTES",
    "build_denial_context",
    "build_denial_payload",
    "emit_denial_event",
]
