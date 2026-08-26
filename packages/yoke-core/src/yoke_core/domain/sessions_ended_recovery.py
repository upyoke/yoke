"""Ended-session registration probe + the recovery command refusals name.

A ``session_id`` legitimately spans episodes: a transient ``SessionEnd``
(laptop sleep, app reload, brief disconnect) closes the
``harness_sessions`` row while the conversation keeps running. Two
surfaces need to agree on what an ended row means, and both live here so
they cannot drift:

* :func:`session_registration_state` — the one-round-trip probe the
  hook-runner ensure-register path uses. It reports ``ended`` alongside
  ``row_found`` so a *closed* row counts as "needs registration": every
  hook-carrying turn (tool-call hooks included, the only empirically
  guaranteed event class) revives the session through the registrar's
  reactivation branch instead of waiting for a lifecycle event that may
  never fire again in this conversation.
* :func:`session_ended_message` — the refusal text for the surfaces that
  still cannot serve an ended session (heartbeat, session mode,
  work-claim acquisition). The stored row already carries every field
  ``yoke sessions begin`` needs, so the message renders a populated,
  copy-pasteable re-register command rather than a dead end.

Both helpers are read-only and never raise: a failed probe reports
"unknown" so callers keep their existing behavior, and a failed render
falls back to the bare refusal sentence.
"""

from __future__ import annotations

import shlex
from typing import Any, Optional, Tuple

from yoke_core.domain import db_backend


#: Registered CLI that re-registers an existing session id and starts a
#: new episode. Rendered with the ended row's own stored identity.
RECOVERY_COMMAND = "yoke sessions begin"

_RECOVERY_PREFIX = "Re-register this session id to start a new episode: "


#: Returned by :func:`_safe_fetchone` when the read itself could not run,
#: so callers never confuse a broken connection with a positive no-row
#: finding.
_LOOKUP_FAILED = object()


def _safe_fetchone(conn: Any, sql: str, params: Tuple[Any, ...]) -> Any:
    """Run one read, savepoint-guarded so a failure cannot poison ``conn``.

    Returns the row, ``None`` on a positive no-row finding, or
    :data:`_LOOKUP_FAILED` when the read could not run at all.
    """
    savepoint = "_yoke_session_registration_state"
    created = False
    try:
        if db_backend.connection_is_postgres(conn):
            conn.execute(f"SAVEPOINT {savepoint}")
            created = True
        row = conn.execute(sql, params).fetchone()
        if created:
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        return row
    except Exception:  # noqa: BLE001 — any read failure is "unknown", never a raise
        # Every caller treats "unknown" as "change nothing", so a probe that
        # raised would turn a transport hiccup into a lost revival or a lost
        # refusal message. Broad by contract, not by accident.
        if created:
            try:
                conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            except Exception:  # noqa: BLE001 — probe must never raise
                pass
        return _LOOKUP_FAILED


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def session_registration_state(
    conn: Any, session_id: str
) -> Tuple[Optional[bool], Optional[int], bool]:
    """Return ``(row_found, actor_id, ended)`` for ``session_id``.

    ``row_found`` is ``True`` when a ``harness_sessions`` row exists,
    ``False`` on a positive no-row finding, and ``None`` when the lookup
    itself failed (so callers can distinguish "unregistered" from
    "unknown"). ``ended`` is ``True`` only for an ordinarily ended row that
    hooks may reactivate. A permanently terminated row deliberately reports
    ``False`` so the caller treats it as registered without driving revival;
    an unknown lookup likewise never claims a session is closed.
    """
    if not session_id:
        return False, None, False
    row = _safe_fetchone(
        conn,
        f"SELECT actor_id, ended_at, terminated_at FROM harness_sessions "
        f"WHERE session_id = {_p(conn)}",
        (session_id,),
    )
    if row is _LOOKUP_FAILED:
        return None, None, False
    if row is None:
        return False, None, False
    try:
        return (
            True,
            row["actor_id"],
            row["ended_at"] is not None and row["terminated_at"] is None,
        )
    except Exception:  # noqa: BLE001 — an unreadable row is "unknown", not a raise
        return None, None, False


def session_ended_recovery_command(conn: Any, session_id: str) -> str:
    """Render the populated ``yoke sessions begin`` line for an ended row.

    Returns an empty string when the row or its identity columns cannot be
    read — the caller then keeps the bare refusal sentence.
    """
    row = _safe_fetchone(
        conn,
        f"SELECT executor, provider, model, workspace, project_id "
        f"FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    )
    if row is _LOOKUP_FAILED or row is None:
        return ""
    flags = [("--session-id", session_id)]
    for flag, column in (
        ("--executor", "executor"),
        ("--provider", "provider"),
        ("--model", "model"),
        ("--workspace", "workspace"),
    ):
        value = row[column]
        if not value:
            return ""
        flags.append((flag, str(value)))
    project_id = row["project_id"]
    if project_id is not None:
        flags.append(("--project", str(project_id)))
    rendered = " ".join(f"{flag} {shlex.quote(value)}" for flag, value in flags)
    return f"{RECOVERY_COMMAND} {rendered}"


def session_ended_message(conn: Any, session_id: str) -> str:
    """Return the ``SESSION_ENDED`` refusal text, recovery command included.

    Every registered surface that refuses an ended session shares this
    sentence so the operator always reads the same recovery recipe.
    """
    row = _safe_fetchone(
        conn,
        f"SELECT terminated_at FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    )
    if row is not _LOOKUP_FAILED and row is not None and row["terminated_at"]:
        return f"Session '{session_id}' has been permanently terminated."
    base = f"Session '{session_id}' has already ended."
    try:
        command = session_ended_recovery_command(conn, session_id)
    except Exception:  # noqa: BLE001 — guidance must never mask the refusal
        command = ""
    if not command:
        return base
    return f"{base} {_RECOVERY_PREFIX}{command}"


__all__ = [
    "RECOVERY_COMMAND",
    "session_ended_message",
    "session_ended_recovery_command",
    "session_registration_state",
]
