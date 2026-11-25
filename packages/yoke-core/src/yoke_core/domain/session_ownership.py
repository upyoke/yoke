"""Actor ownership policy for stamped session identities."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from yoke_core.domain import db_backend, db_helpers


def session_ownership_refusal(
    conn: Any,
    session_id: str,
    actor_id: int | None,
) -> str | None:
    """Refuse a stamped id whose existing session belongs to another actor.

    An id with no session row yet is accepted: the observation itself is
    what registers a session that a hook has only just started stamping.
    """
    if actor_id is None or not session_id:
        return None
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT actor_id FROM harness_sessions WHERE session_id = {marker}",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    stored = row.get("actor_id") if isinstance(row, dict) else row[0]
    if stored is None or int(stored) == int(actor_id):
        return None
    return (
        "stamped session id belongs to a different actor; relay through the "
        "connection whose actor owns the session"
    )


def delegated_launch_actor(
    *, session_id: str, machine_id: str, token_actor_id: int, conn: Any = None
) -> int | None:
    """Resolve only an active, exact launch on the token's own machine.

    A machine credential alone grants no actor substitution. The requester
    chose this machine for the launch, its attestation bound the native
    session, and the registered actor must still be that requester.
    """
    with nullcontext(conn) if conn is not None else db_helpers.connect() as conn:
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            "SELECT s.actor_id FROM harness_sessions s "
            "JOIN session_launches l ON l.registered_session_id=s.session_id "
            "JOIN machines m ON m.machine_id=s.machine_id "
            f"WHERE s.session_id={p} AND s.machine_id={p} "
            "AND s.ended_at IS NULL AND s.terminated_at IS NULL "
            "AND l.native_session_id=s.session_id "
            "AND l.assigned_machine_id=s.machine_id "
            "AND l.project_id=s.project_id "
            "AND l.requester_actor_id=s.actor_id "
            "AND l.attestation_consumed_at IS NOT NULL "
            "AND l.state IN ('awaiting_registration','succeeded') "
            f"AND m.owner_actor_id={p} AND m.retired_at IS NULL "
            "LIMIT 1",
            (session_id, machine_id, token_actor_id),
        ).fetchone()
    return int(row[0]) if row is not None and row[0] is not None else None
