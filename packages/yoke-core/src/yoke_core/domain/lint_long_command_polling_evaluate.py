"""Polling verdicts and session-scoped capture registration lookup."""

from __future__ import annotations

from datetime import datetime, timedelta
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.db_helpers import instant_parameter
from typing import Optional, Sequence

from yoke_contracts.hook_runner.client_facts import (
    capture_roots,
)
from yoke_contracts.hook_runner.shell_parse import ShellParse

from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain.lint_long_command_polling_constants import (
    RECENT_EVENT_LOOKBACK_SECONDS,
    SLEEP_CADENCE_FLOOR_SECONDS,
)
from yoke_core.domain.lint_long_command_polling_decide import (
    _build_context,
    _format_github_poll_loop_reason,
    _format_sleep_reason,
)
from yoke_core.domain.lint_long_command_polling_extract import (
    _extract_background_capture_files,
    _extract_command,
    _extract_sleep_cadence,
    _extract_sleep_capture_file,
    _has_suppression,
    _is_github_poll_loop,
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
) -> list[tuple[str, datetime | None, str]]:
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
    cutoff = utc_now() - timedelta(seconds=int(lookback_seconds))
    try:
        rows = conn.execute(
            "SELECT tool_use_id, completed_at, command_summary "
            "FROM session_tool_calls WHERE session_id=%s "
            "AND tool_name='Bash' AND completed_at IS NOT NULL "
            "AND completed_at > %s "
            "ORDER BY completed_at DESC LIMIT 100",
            (session_id, instant_parameter(conn, cutoff)),
        ).fetchall()
    except db_backend.operational_error_types(conn=conn):
        return []
    finally:
        conn.close()
    out: list[tuple[str, datetime | None, str]] = []
    for tool_use_id, completed_at, command in rows:
        if not isinstance(command, str) or not command:
            continue
        out.append((tool_use_id or "", completed_at, command))
    return out


def _capture_registered_in_session(
    recent: list[tuple[str, datetime | None, str]],
    capture_file: str,
    roots: Sequence[str],
) -> bool:
    """True if a recent session command registered *capture_file* as a capture.

    Registration = a prior Bash command redirected into the file or named
    it via a watcher ``--raw-capture``/``--progress-capture`` arg
    (:func:`_extract_background_capture_files`). A /tmp file no session
    command owns this way is not a live capture — e.g. a pointer note
    persisting a mktemp path across Bash subshells.
    """
    return any(
        capture_file in _extract_background_capture_files(cmd, roots)
        for _tool_use_id, _created_at, cmd in recent
    )


def evaluate_payload(
    payload: dict,
    tool_name: Optional[str] = None,
    shell: Optional[ShellParse] = None,
) -> Optional[tuple[str, dict]]:
    """Evaluate *payload*. Return ``(reason, context)`` or ``None``.

    *tool_name* is the runner's tool name; ``None`` reads the payload's
    ``tool_name``. *shell* is the hook's shared parse of the command. The
    returned context dict may carry an ``outcome`` key
    for rules with audit-only suppression tokens.
    """
    if tool_name is None:
        raw_tool = payload.get("tool_name")
        tool_name = raw_tool if isinstance(raw_tool, str) else ""
    command = _extract_command(payload)

    # A GitHub polling loop holds the turn a recorded CI wait would end;
    # checked before the suppression token, which does not unblock it.
    if (
        tool_name in ("", "Bash")
        and command
        and _is_github_poll_loop(shell if shell is not None else command)
    ):
        ctx = _build_context(tool_name or "Bash", command, None)
        return _format_github_poll_loop_reason(), ctx

    if command and _has_suppression(command):
        return None

    # Monitor: dispatch to the duplicate-Monitor verdict.
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

    # Only a short wait followed by a read of a session-owned capture polls.
    cadence = _extract_sleep_cadence(command)
    if cadence is None or cadence >= SLEEP_CADENCE_FLOOR_SECONDS:
        return None
    roots = capture_roots(payload)
    capture_file = _extract_sleep_capture_file(command, roots)
    if capture_file is None:
        return None
    session_id = payload.get("session_id") or ""
    recent = _recent_bash_commands("", session_id) if _db_available() else []
    if not _capture_registered_in_session(recent, capture_file, roots):
        return None
    ctx = _build_context(tool_name or "Bash", command, capture_file)
    return _format_sleep_reason(cadence), ctx
