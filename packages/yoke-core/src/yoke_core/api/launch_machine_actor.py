"""Bind a relay worker's HTTPS calls to its attested launch actor."""

from __future__ import annotations

from typing import Any

from yoke_core.api.http_auth import HttpAuthContext, bind_actor_from_auth
from yoke_core.domain import db_backend, db_helpers


def _delegated_actor(
    *, session_id: str, machine_id: str, token_actor_id: int
) -> int | None:
    """Resolve only an active, exact launch on the token's own machine.

    A machine credential alone grants no actor substitution. The requester
    chose this machine for the launch, its attestation bound the native
    session, and the registered actor must still be that requester.
    """
    with db_helpers.connect() as conn:
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


def bind_actor_for_session(
    envelope: dict[str, Any], auth: HttpAuthContext
) -> tuple[dict[str, Any], str | None]:
    """Use the token actor except for its exact attested relay launch.

    The client-supplied actor is always discarded. The dispatcher still
    checks the resulting actor against ``harness_sessions`` and applies the
    registered function's ordinary claim and permission gates.
    """
    bound, session_id = bind_actor_from_auth(envelope, auth)
    if not session_id or not auth.machine_id:
        return bound, session_id
    actor_id = _delegated_actor(
        session_id=session_id,
        machine_id=auth.machine_id,
        token_actor_id=auth.actor_id,
    )
    if actor_id is not None:
        actor = dict(bound["actor"])
        actor["actor_id"] = str(actor_id)
        bound["actor"] = actor
    return bound, session_id


__all__ = ["bind_actor_for_session"]
