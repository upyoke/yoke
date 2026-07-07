"""Session touch + heartbeat command handlers, plus the active-session validator.

Owns the CLI surface for ``service-client session-heartbeat`` and
``service-client session-touch`` and the ``_validate_active_session`` helper
used by claim acquire/release commands.
"""

from __future__ import annotations

import json
import sys

from yoke_core.domain import db_backend
from yoke_core.api.service_client_shared import (
    SESSION_REQUIRED_ERROR,
    _get_db_readwrite,
    _resolve_session_id,
    domain_heartbeat,
    set_session_mode,
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def cmd_session_heartbeat(args: list[str]) -> int:
    """Refresh a session heartbeat and all active claim heartbeats.

    Usage: session-heartbeat --session-id S

    Best-effort: exits 0 even if the session is already ended or not found.
    Prints result JSON to stdout.

    On-demand only: the keepalive loop has been removed (events are the
    canonical liveness signal). The PreToolUse heartbeat hook refreshes
    activity at agent turn boundaries.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="session-heartbeat", add_help=False)
    parser.add_argument("--session-id", default=None)

    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        print(
            "Usage: session-heartbeat [--session-id S]",
            file=sys.stderr,
        )
        return 2

    parsed.session_id = _resolve_session_id(parsed.session_id)
    if not parsed.session_id:
        print(SESSION_REQUIRED_ERROR, file=sys.stderr)
        return 2

    conn = _get_db_readwrite()
    try:
        from yoke_core.domain.sessions import SessionError
        try:
            result = domain_heartbeat(conn, parsed.session_id)
            print(json.dumps({"success": True, "session": result}))
        except SessionError as exc:
            print(json.dumps({
                "success": True,
                "already_ended": True,
                "code": exc.code,
                "message": exc.message,
            }))
        return 0
    finally:
        conn.close()


def cmd_session_touch(args: list[str]) -> int:
    """Heartbeat an active session and optionally update its mode.

    Usage: session-touch --session-id S [--mode M]

    When --mode is provided, calls both heartbeat() and set_session_mode().
    When --mode is omitted, calls only heartbeat().

    Unlike session-heartbeat (which is best-effort), session-touch returns
    exit 1 with a truthful error on NOT_FOUND or SESSION_ENDED.

    Prints result JSON to stdout.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="session-touch", add_help=False)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--mode", default=None)

    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        print("Usage: session-touch [--session-id S] [--mode M]", file=sys.stderr)
        return 2

    parsed.session_id = _resolve_session_id(parsed.session_id)
    if not parsed.session_id:
        print(SESSION_REQUIRED_ERROR, file=sys.stderr)
        return 2

    conn = _get_db_readwrite()
    try:
        from yoke_core.domain.sessions import SessionError
        try:
            result = domain_heartbeat(conn, parsed.session_id)
            if parsed.mode is not None:
                set_session_mode(conn, parsed.session_id, parsed.mode)
                result["mode"] = parsed.mode
            print(json.dumps({"success": True, "session": result}, default=str))
            return 0
        except SessionError as exc:
            if exc.code == "NOT_FOUND":
                msg = (f"Error: session {parsed.session_id} not found. "
                       "Ensure session-begin was called at session start.")
            elif exc.code == "SESSION_ENDED":
                msg = (f"Error: session {parsed.session_id} has ended. "
                       "Cannot claim work on an inactive session.")
            else:
                msg = f"Error: {exc.message}"
            print(json.dumps({"error": exc.code, "message": msg}),
                  file=sys.stderr)
            return 1
    finally:
        conn.close()


def _validate_active_session(conn, session_id: str) -> bool:
    """Check that *session_id* references an active (not ended, not missing) session.

    Returns ``True`` when the session is active.  On failure, prints a JSON
    error object to **stderr** and returns ``False``.
    """
    p = _p(conn)
    row = conn.execute(
        f"SELECT ended_at FROM harness_sessions WHERE session_id = {p}",
        (session_id,),
    ).fetchone()

    if row is None:
        print(json.dumps({
            "success": False,
            "error": ("Error: no active session. Session must be started by "
                      "harness hook or /yoke do before claiming work."),
        }), file=sys.stderr)
        return False

    if row["ended_at"] is not None:
        print(json.dumps({
            "success": False,
            "error": (f"Error: session {session_id} has ended. "
                      "Cannot claim work on an inactive session."),
        }), file=sys.stderr)
        return False

    return True


__all__ = [
    "cmd_session_heartbeat",
    "cmd_session_touch",
    "_validate_active_session",
]
