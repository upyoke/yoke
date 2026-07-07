"""Verdict logic for the long-command polling lint.

Owns ``evaluate_payload`` plus the I/O-touching helpers it consumes:

- session-scoped DB lookup (``_db_available``,
  ``_recent_bash_commands``, ``_count_prior_peeks_in_window``)
- the mtime "owning command still running" signal
  (``_owning_command_still_running``)

Pure command/payload introspection helpers live on the extract sibling.
Reason formatters, audit emission, and the deny envelope live on the
decide sibling. Mode/config reads (``_read_lint_mode``) stay on the
entry-point — this module imports them.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain.lint_long_command_polling_completion import capture_file_completed
from yoke_core.domain.lint_long_command_polling_config import _read_lint_mode
from yoke_core.domain.lint_long_command_polling_constants import (
    MTIME_ACTIVE_THRESHOLD_SECONDS,
    PEEK_WINDOW_TURNS,
    RECENT_EVENT_LOOKBACK_SECONDS,
    SLEEP_CADENCE_FLOOR_SECONDS,
)
from yoke_core.domain.lint_long_command_polling_decide import (
    _build_context,
    _format_peek_reason,
    _format_sleep_reason,
)
from yoke_core.domain.lint_long_command_polling_extract import (
    _extract_background_capture_files,
    _extract_command,
    _extract_peek_capture_file,
    _extract_sleep_cadence,
    _extract_tool_name,
    _has_suppression,
    _peek_read_in_command_substitution,
)
from yoke_core.domain.lint_long_command_polling_monitor_duplicate import (
    evaluate_duplicate_monitor,
)
from yoke_core.domain.lint_long_command_polling_waiter import (
    evaluate_bg_waiter,
)


def _db_available() -> bool:
    try:
        db_backend.resolve_pg_dsn()
    except Exception:
        return False
    return True


def _recent_bash_commands(
    db_path: str,
    session_id: str,
    lookback_seconds: int = RECENT_EVENT_LOOKBACK_SECONDS,
) -> list[tuple[str, str, str]]:
    """Return ``(tool_use_id, completed_at, command)`` for recent Bash calls.

    Pulls completed ``session_tool_calls`` rows for ``tool_name='Bash'``
    in the named session within the lookback window, most recent first.
    ``command_summary`` is the bounded command text the observe pipeline
    records per call (truncated, sufficient for capture-file extraction).
    Silently returns ``[]`` on any DB error so the hook never blocks tool
    execution.
    """
    if not session_id:
        return []
    try:
        conn = db_helpers.connect(db_path or None)
    except db_backend.operational_error_types() + (RuntimeError,):
        return []
    cutoff = (
        datetime.now(timezone.utc) - timedelta(seconds=int(lookback_seconds))
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        rows = conn.execute(
            "SELECT tool_use_id, completed_at, command_summary "
            "FROM session_tool_calls WHERE session_id=%s "
            "AND tool_name='Bash' AND completed_at IS NOT NULL "
            "AND completed_at > %s "
            "ORDER BY completed_at DESC LIMIT 100",
            (session_id, cutoff),
        ).fetchall()
    except db_backend.operational_error_types(conn=conn):
        return []
    finally:
        conn.close()
    out: list[tuple[str, str, str]] = []
    for tool_use_id, completed_at, command in rows:
        if not isinstance(command, str) or not command:
            continue
        out.append((tool_use_id or "", completed_at or "", command))
    return out


def _count_prior_peeks_in_window(
    recent: list[tuple[str, str, str]],
    capture_file: str,
    current_tool_use_id: str,
    window_turns: int = PEEK_WINDOW_TURNS,
) -> int:
    """Count prior Bash peeks targeting *capture_file* in the last *window_turns*.

    "Window" is measured as distinct ``tool_use_id``s immediately preceding
    the current one. The current invocation is NOT counted — callers add 1
    to ask "is this the Nth peek."
    """
    seen: list[str] = []
    count = 0
    for tool_use_id, _created_at, command in recent:
        if not tool_use_id or tool_use_id == current_tool_use_id:
            continue
        if tool_use_id not in seen:
            seen.append(tool_use_id)
            if len(seen) > window_turns:
                break
        peek_target = _extract_peek_capture_file(command)
        if peek_target == capture_file:
            count += 1
    return count


def _capture_registered_in_session(
    recent: list[tuple[str, str, str]], capture_file: str
) -> bool:
    """True if a recent session command registered *capture_file* as a capture.

    Registration = a prior Bash command redirected into the file or named
    it via a watcher ``--raw-capture``/``--progress-capture`` arg
    (:func:`_extract_background_capture_files`). A /tmp file no session
    command owns this way is not a live capture — e.g. a pointer note
    persisting a mktemp path across Bash subshells.
    """
    return any(
        capture_file in _extract_background_capture_files(cmd)
        for _tool_use_id, _created_at, cmd in recent
    )


def _owning_command_still_running(capture_file: str) -> bool:
    """Return True if *capture_file*'s owning command is still running.

    Checks the watcher exit sentinel first (:func:`capture_file_completed`):
    once written the command has exited regardless of mtime, so the single
    sanctioned post-completion ``tail -80 <raw-capture>`` is allowed
    (ouroboros 8857 / 8873). Otherwise the mtime heuristic applies: a
    capture touched within :data:`MTIME_ACTIVE_THRESHOLD_SECONDS` is still
    being appended to, so a genuine mid-run peek stays denied.
    """
    if capture_file_completed(capture_file):
        return False
    try:
        stat_result = os.stat(capture_file)
    except OSError:
        return False
    age_seconds = time.time() - stat_result.st_mtime
    return age_seconds < MTIME_ACTIVE_THRESHOLD_SECONDS


def evaluate_payload(payload: dict) -> Optional[tuple[str, str, dict]]:
    """Evaluate *payload*. Return ``(verdict, reason, context)`` or ``None``.

    ``verdict`` is one of ``warn`` or ``deny``. The caller decides how to
    surface each: ``deny`` emits ``hookSpecificOutput`` with
    ``permissionDecision=deny``; ``warn`` emits the audit event only.

    The returned context dict may carry an ``outcome`` key for rules with
    audit-only suppression tokens.
    """
    tool_name = _extract_tool_name(payload)
    command = _extract_command(payload)

    if command and _has_suppression(command):
        return None

    mode = _read_lint_mode(payload)

    # Monitor: dispatch to the duplicate-Monitor verdict.
    # Detection-only; mode follows lint_polling_mode (warn/deny).
    if tool_name == "Monitor":
        return evaluate_duplicate_monitor(payload)

    if tool_name and tool_name != "Bash":
        return None

    if not command:
        return None

    # Bash(run_in_background=true) waiter shapes: another long bg whose
    # body is `tail -f <capture>`, `sleep N && tail/cat <capture>`,
    # `while [ ! -f <sentinel> ]; do sleep N; done`, or
    # `watch_tail <existing-capture>`. Dispatch to the waiter sibling
    # before the foreground branches; it returns None when the candidate
    # is not run-in-background or the body does not match a waiter shape.
    waiter_verdict = evaluate_bg_waiter(payload)
    if waiter_verdict is not None:
        return waiter_verdict

    # sleep N && peek with N below the floor
    cadence = _extract_sleep_cadence(command)
    if cadence is not None and cadence < SLEEP_CADENCE_FLOOR_SECONDS:
        ctx = _build_context(tool_name or "Bash", command, None)
        return (mode, _format_sleep_reason(cadence, mode), ctx)

    capture_file = _extract_peek_capture_file(command)

    # Capture-file peek: check if owning command still running and whether
    # this is a repeated peek within the window.
    if capture_file is not None:
        still_running = _owning_command_still_running(capture_file)
        if not still_running:
            # Owning command completed — post-capture inspection is allowed.
            return None

        session_id = payload.get("session_id") or ""
        current_tool_use_id = (
            payload.get("tool_use_id")
            or payload.get("turn_id")
            or payload.get("message_id")
            or ""
        )
        recent = (
            _recent_bash_commands("", session_id) if _db_available() else []
        )

        # Pointer-file carve-out: a command-substitution read of a file
        # no session command owns as a capture is content consumption,
        # not a progress peek (the mtime heuristic alone cannot tell a
        # freshly written pointer note from a live capture).
        if _peek_read_in_command_substitution(
            command
        ) and not _capture_registered_in_session(recent, capture_file):
            return None

        prior_peeks = _count_prior_peeks_in_window(
            recent, capture_file, current_tool_use_id
        )

        if prior_peeks >= 1:
            ctx = _build_context(tool_name or "Bash", command, capture_file)
            return (mode, _format_peek_reason(capture_file, prior_peeks, mode), ctx)
        return None

    return None
