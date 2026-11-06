"""Refuse duplicate live Monitor subscriptions until their stored deadlines."""

from __future__ import annotations

from datetime import timedelta
from yoke_contracts.timestamps import utc_now, format_instant, parse_instant
from yoke_core.domain.db_helpers import instant_parameter
from typing import Optional, Sequence

from yoke_contracts.hook_runner.client_facts import capture_roots
from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain.lint_long_command_polling_decide import (
    _build_context,
    _format_monitor_duplicate_reason,
)
from yoke_core.domain.lint_long_command_polling_extract import (
    _extract_command,
    _extract_monitor_capture_file,
    _has_monitor_duplicate_suppression,
)


def _db_available() -> bool:
    """Indirection layer over :mod:`db_helpers`.

    Imported lazily to avoid a hard dependency at module import time —
    the lint module never raises on a missing DB. Returns ``False``
    when the lookup fails for any reason.
    """
    try:
        db_backend.resolve_pg_dsn()
    except Exception:
        return False
    return True


def _captures_targeted_in_session(
    db_path: str,
    session_id: str,
    roots: Sequence[str],
) -> list[tuple[str, str, str]]:
    """Return live capture subscriptions, including completed setup calls."""
    if not session_id:
        return []
    try:
        conn = db_helpers.connect(db_path or None)
    except db_backend.operational_error_types() + (RuntimeError,):
        return []
    try:
        rows = conn.execute(
            """
            SELECT tool_use_id, command_summary, monitor_deadline_at
              FROM session_tool_calls
             WHERE session_id = %s
               AND tool_name = 'Monitor'
               AND command_summary IS NOT NULL
               AND monitor_deadline_at > %s
               AND (outcome IS NULL OR outcome = 'completed')
             ORDER BY started_at ASC
             LIMIT 200
            """,
            (
                session_id,
                instant_parameter(
                    conn, utc_now() + timedelta(seconds=EXPIRY_MARGIN_SECONDS)
                ),
            ),
        ).fetchall()
    except db_backend.operational_error_types(conn=conn):
        return []
    finally:
        conn.close()

    targeted: dict[str, tuple[str, str]] = {}
    for tool_use_id, command, deadline in rows:
        if not tool_use_id or not isinstance(command, str) or not command:
            continue
        capture_file = _extract_monitor_capture_file(command, roots)
        if not capture_file:
            continue
        # First-seen wins on tool_use_id collisions; preserves "earliest
        # Monitor against this capture" semantics for the reason text.
        targeted.setdefault(
            tool_use_id, (capture_file, format_instant(parse_instant(deadline)))
        )
    return [(key, *value) for key, value in targeted.items()]


#: Slack for when the harness started the clock versus when the tool call
#: was recorded, so a re-arm on the expiry notice is never refused.
EXPIRY_MARGIN_SECONDS = 60


def evaluate_duplicate_monitor(
    payload: dict,
) -> Optional[tuple[str, dict]]:
    """Verdict for the duplicate-Monitor PreToolUse rule on a Monitor call.

    Returns ``(reason, context)`` when the candidate ``Monitor``
    invocation targets a capture file that already has an armed Monitor
    in the same session, or ``None`` when the rule does not fire. The
    caller dispatches only Monitor calls here.

    The ``# lint:no-monitor-duplicate-check`` token is honoured ONLY as
    audit evidence: when detected, the context's ``outcome`` becomes
    ``suppression_attempted`` but the verdict still fires.
    """
    tool_name = "Monitor"
    command = _extract_command(payload)
    if not command:
        return None
    roots = capture_roots(payload)
    candidate_capture = _extract_monitor_capture_file(command, roots)
    if not candidate_capture:
        return None
    session_id = payload.get("session_id") or ""
    if not session_id or not _db_available():
        return None
    targeted = _captures_targeted_in_session("", session_id, roots)
    prior_tool_use_id = ""
    deadline = ""
    for tool_use_id, capture_file, effective_deadline in targeted:
        if capture_file == candidate_capture and tool_use_id != payload.get(
            "tool_use_id"
        ):
            deadline = effective_deadline
            prior_tool_use_id = tool_use_id
            break
    if not prior_tool_use_id:
        return None
    suppressed_attempt = _has_monitor_duplicate_suppression(command)
    ctx = _build_context(tool_name, command, candidate_capture)
    ctx["outcome"] = "suppression_attempted" if suppressed_attempt else "denied"
    reason = _format_monitor_duplicate_reason(
        candidate_capture,
        prior_tool_use_id,
        suppressed_attempt,
        deadline,
    )
    return reason, ctx
