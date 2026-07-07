"""Duplicate-Monitor PreToolUse verdict.

Split sibling of :mod:`lint_long_command_polling_evaluate`. Owns the
"second ``Monitor`` against the same capture file is denied" rule plus
its DB-touching helper (``_captures_targeted_in_session``). Lives in a
dedicated module so the main evaluate file stays under the 350-line
authored-file cap.

The entry point :func:`evaluate_duplicate_monitor` is mode-pinned
(``lint_polling_mode`` ``warn`` records audit only; ``deny`` blocks),
honours the ``# lint:no-monitor-duplicate-check`` suppression token
ONLY as audit evidence (the rule still denies in ``deny`` mode), and
is re-exported from ``yoke_core.domain.lint_long_command_polling`` so
external callers can import it from that entry-point path.

Detection model:

1. The candidate Monitor command's capture file is extracted via
   :func:`_extract_monitor_capture_file` (covers ``watch_tail`` and
   bare ``tail -f`` shapes; the trailing filter is irrelevant).
2. ``session_tool_calls`` is queried for every Monitor row in this
   session. Capture files are extracted from ``command_summary``
   (recorded by the observe pipeline at Started time).
3. When ANY prior Monitor in this session targeted the candidate's
   capture file — regardless of whether that Monitor is still armed
   or has already completed — the verdict fires. Operational data
   showed that the dominant failure mode is post-completion re-arms
   in a wake loop: Monitor's tool_use completes within ~0.3s of
   setup, the agent re-arms, each re-arm spawns a fresh ``watch_tail``
   subprocess against the same capture file, and dozens accumulate
   over a multi-minute background command. The fire-once-per-capture
   contract now spans the whole session for each capture path.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain.lint_long_command_polling_config import _read_lint_mode
from yoke_core.domain.lint_long_command_polling_constants import (
    RECENT_EVENT_LOOKBACK_SECONDS,
)
from yoke_core.domain.lint_long_command_polling_decide import (
    _build_context,
    _format_monitor_duplicate_reason,
)
from yoke_core.domain.lint_long_command_polling_extract import (
    _extract_command,
    _extract_monitor_capture_file,
    _extract_tool_name,
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
    lookback_seconds: int = RECENT_EVENT_LOOKBACK_SECONDS,
) -> list[tuple[str, str]]:
    """Return ``(tool_use_id, capture_file)`` for every Monitor in session.

    Includes both still-armed (open) and already-completed Monitor rows
    within the lookback window. The fire-once-per-capture contract spans
    the whole session: once a capture file has been targeted by Monitor
    at all, a second Monitor against it is a wake-loop re-arm. The
    capture file is for post-completion inspection via ``tail -80
    <raw>``, not for repeat-arming.

    ``session_tool_calls.command_summary`` carries the Monitor command
    body (recorded by the observe pipeline at Started time); we parse
    the capture-file path out of it.

    Silently returns ``[]`` on any DB error so the hook never blocks
    tool execution because of a state-side failure.
    """
    if not session_id:
        return []
    try:
        conn = db_helpers.connect(db_path or None)
    except db_backend.operational_error_types() + (RuntimeError,):
        return []
    try:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(seconds=int(lookback_seconds))
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = conn.execute(
            """
            SELECT tool_use_id, command_summary
              FROM session_tool_calls
             WHERE session_id = %s
               AND tool_name = 'Monitor'
               AND command_summary IS NOT NULL
               AND started_at > %s
             ORDER BY started_at ASC
             LIMIT 200
            """,
            (session_id, cutoff),
        ).fetchall()
    except db_backend.operational_error_types(conn=conn):
        return []
    finally:
        conn.close()

    targeted: dict[str, str] = {}
    for tool_use_id, command in rows:
        if not tool_use_id or not isinstance(command, str) or not command:
            continue
        capture_file = _extract_monitor_capture_file(command)
        if not capture_file:
            continue
        # First-seen wins on tool_use_id collisions; preserves "earliest
        # Monitor against this capture" semantics for the reason text.
        targeted.setdefault(tool_use_id, capture_file)
    return list(targeted.items())


def evaluate_duplicate_monitor(
    payload: dict,
) -> Optional[tuple[str, str, dict]]:
    """Verdict for the duplicate-Monitor PreToolUse rule.

    Returns ``(mode, reason, context)`` when the candidate ``Monitor``
    invocation targets a capture file that already has an armed Monitor
    in the same session, or ``None`` when the rule does not fire.

    Mode-pinned by ``lint_polling_mode`` (``warn`` records audit only;
    ``deny`` blocks). The ``# lint:no-monitor-duplicate-check`` token
    is honoured ONLY as audit evidence: when detected, the context's
    ``outcome`` becomes ``suppression_attempted`` but the verdict still
    fires.
    """
    tool_name = _extract_tool_name(payload)
    if tool_name != "Monitor":
        return None
    command = _extract_command(payload)
    if not command:
        return None
    candidate_capture = _extract_monitor_capture_file(command)
    if not candidate_capture:
        return None
    session_id = payload.get("session_id") or ""
    if not session_id or not _db_available():
        return None
    targeted = _captures_targeted_in_session("", session_id)
    prior_tool_use_id = ""
    for tool_use_id, capture_file in targeted:
        if capture_file == candidate_capture:
            prior_tool_use_id = tool_use_id
            break
    if not prior_tool_use_id:
        return None
    mode = _read_lint_mode(payload)
    suppressed_attempt = _has_monitor_duplicate_suppression(command)
    ctx = _build_context(tool_name, command, candidate_capture)
    ctx["outcome"] = (
        "suppression_attempted" if suppressed_attempt else "denied"
    )
    reason = _format_monitor_duplicate_reason(
        candidate_capture, prior_tool_use_id, suppressed_attempt, mode,
    )
    return (mode, reason, ctx)
