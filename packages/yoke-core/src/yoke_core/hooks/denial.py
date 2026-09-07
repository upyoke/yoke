"""Denial event payload construction and emission for hook guards.

Builds the ``HarnessToolCallDenied`` context payload from a hook /
check / reason tuple and pushes it through the native
``yoke_core.domain.events.emit_event`` CLI. Imported by lint guards
that need only the denial path; ``yoke_core.hooks.telemetry``
re-exports the public surface so call sites can ``mock.patch`` against
``yoke_core.hooks.telemetry.emit_denial_event``.

A refused call is also *finished*, and this module closes it. The
PreToolUse observation opens a ``session_tool_calls`` row and the tool
then never runs, so nothing else ever closes it — which left the fleet
report reading a permanently open row as a worker inside a long command,
and forced it to join the telemetry ledger just to tell a refusal from a
running command. Closing the row here makes the call's own recorded
outcome the answer, and it survives whatever telemetry retention does.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain.events_tool_call_outcome import OUTCOME_DENIED


COMMAND_SNIPPET_MAX_BYTES = 512

#: The one event name this module emits, and the outcome it records on
#: the refused call's own row.
DENIAL_EVENT_NAME = "HarnessToolCallDenied"


def build_denial_payload(
    hook: str = "",
    check_id: str = "",
    reason: str = "",
    command_snippet: str = "",
    guard_key: str = "",
    mode: str = "",
    client_revision: str = "",
    server_revision: str = "",
    guard_version_skew: str = "",
) -> dict[str, Any]:
    """Build the context payload for a HarnessToolCallDenied event.

    ``guard_key``/``mode`` name the lint-config guard and the mode it
    resolved under (``deny``/``warn``); ``client_revision``/
    ``server_revision`` record the source revision each side of a relayed
    evaluation was running, so a denial recorded during guard-revision skew
    carries the pair that explains it.
    """
    payload = {
        "hook": hook,
        "check_id": check_id,
        "reason": reason.replace("\n", " ")[:500],
    }
    if command_snippet:
        payload["command_snippet"] = command_snippet.replace("\n", " ")[
            :COMMAND_SNIPPET_MAX_BYTES
        ]
    if guard_key:
        payload["guard_key"] = guard_key
    if mode:
        payload["mode"] = mode
    if guard_version_skew:
        payload["guard_version_skew"] = {
            "reason": guard_version_skew.replace("\n", " ")[:500],
            "revision_pair": {
                "client": client_revision,
                "server": server_revision,
            },
        }
    elif client_revision or server_revision:
        payload["revision_pair"] = {
            "client": client_revision,
            "server": server_revision,
        }
    return payload


def build_denial_context(
    hook: str = "",
    check_id: str = "",
    reason: str = "",
    command_snippet: str = "",
    guard_key: str = "",
    mode: str = "",
    client_revision: str = "",
    server_revision: str = "",
    guard_version_skew: str = "",
) -> str:
    """Build the compact JSON context for a HarnessToolCallDenied event."""
    return json.dumps(
        build_denial_payload(
            hook=hook,
            check_id=check_id,
            reason=reason,
            command_snippet=command_snippet,
            guard_key=guard_key,
            mode=mode,
            client_revision=client_revision,
            server_revision=server_revision,
            guard_version_skew=guard_version_skew,
        ),
        separators=(",", ":"),
    )


def _close_denied_call(
    *,
    session_id: str,
    tool_use_id: str,
    tool_name: str,
    outcome: str,
) -> None:
    """Stamp the refused call's own row with the outcome that ended it.

    Only a real denial closes the row. ``warn`` and
    ``suppression_attempted`` are audit outcomes on a call the guardrail
    let through, so the tool still runs and its own completion is what
    closes it.

    Runs where the control plane is local — in-process on a local
    universe, and server-side for a relayed client, which reaches this
    same function through the denial-audit route rather than writing from
    the client. A client with no local authority has nothing to write to
    and returns.
    """
    if outcome != OUTCOME_DENIED or not session_id or not tool_use_id:
        return
    from yoke_core.domain import db_backend
    from yoke_core.domain.control_plane_transport import local_connection_or_none
    from yoke_core.domain.session_activity_state import record_tool_call_finished
    from yoke_core.domain.session_message_types import timestamp, utc_now

    conn = local_connection_or_none(db_backend.connect)
    if conn is None:
        return
    try:
        record_tool_call_finished(
            conn,
            session_id=session_id,
            tool_use_id=tool_use_id,
            tool_name=tool_name or None,
            event_name=DENIAL_EVENT_NAME,
            outcome=outcome,
            completed_at=timestamp(utc_now()),
            bump_activity=False,
        )
        conn.commit()
    except Exception:  # noqa: BLE001 - audit path never breaks the refusal
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


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
    guard_key: str = "",
    mode: str = "",
    client_revision: str = "",
    server_revision: str = "",
    guard_version_skew: str = "",
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
        guard_key=guard_key,
        mode=mode,
        client_revision=client_revision,
        server_revision=server_revision,
        guard_version_skew=guard_version_skew,
    )
    if tool_use_id:
        payload["tool_use_id"] = tool_use_id
    if turn_id:
        payload["turn_id"] = turn_id
    _close_denied_call(
        session_id=session_id,
        tool_use_id=tool_use_id,
        tool_name=tool,
        outcome=outcome or OUTCOME_DENIED,
    )
    try:
        from yoke_core.domain import emit_event as emit_event_cli

        parser = emit_event_cli.build_parser()
        args = parser.parse_args(
            [
                "--name",
                DENIAL_EVENT_NAME,
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
    "DENIAL_EVENT_NAME",
    "build_denial_context",
    "build_denial_payload",
    "emit_denial_event",
]
