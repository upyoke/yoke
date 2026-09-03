"""Name the person and machine holding a steering seat.

A seat refusal is read by someone deciding whether to ask for the seat, take
a narrower one, or take over the machine. "Session 5ba2fab5" answers none of
those questions, so a refusal names the actor holding the seat and the
machine it is running on, with the session id kept as the precise handle.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.actor_display import actor_display_name
from yoke_core.domain.actors import ActorError
from yoke_core.domain.schema_common import _table_exists


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _session_facts(conn: Any, session_id: str) -> dict[str, Any]:
    row = conn.execute(
        f"SELECT actor_id, machine_id FROM harness_sessions "
        f"WHERE session_id = {_marker(conn)}",
        (str(session_id),),
    ).fetchone()
    return {} if row is None else dict(row)


def _machine_name(conn: Any, machine_id: Optional[str]) -> Optional[str]:
    """The machine's hostname when a relay has reported one, else its id."""
    if not machine_id:
        return None
    if not _table_exists(conn, "session_relays"):
        return str(machine_id)
    row = conn.execute(
        f"SELECT hostname FROM session_relays WHERE machine_id = {_marker(conn)} "
        "ORDER BY connected_until DESC LIMIT 1",
        (str(machine_id),),
    ).fetchone()
    hostname = dict(row).get("hostname") if row is not None else None
    return str(hostname) if hostname else str(machine_id)


def actor_name(conn: Any, actor_id: Optional[Any]) -> str:
    if actor_id is None:
        return "an unknown actor"
    try:
        return actor_display_name(conn, int(actor_id))
    except (ActorError, TypeError, ValueError):
        return f"actor {actor_id}"


def holder_facts(conn: Any, session_id: str) -> dict[str, Optional[str]]:
    """The person and machine behind one seat, for listings and projections."""
    facts = _session_facts(conn, str(session_id)) if session_id else {}
    return {
        "holder_actor_label": actor_name(conn, facts.get("actor_id")),
        "holder_machine": _machine_name(conn, facts.get("machine_id")),
    }


def holder_label(conn: Any, claim: Mapping[str, Any]) -> str:
    """Render "<person> on <machine> (session '<id>')" for a seat holder."""
    session_id = str(claim.get("session_id") or "")
    facts = _session_facts(conn, session_id) if session_id else {}
    name = actor_name(conn, facts.get("actor_id"))
    machine = _machine_name(conn, facts.get("machine_id"))
    where = f" on {machine}" if machine else ""
    return f"{name}{where} (session {session_id!r})"


__all__ = ["actor_name", "holder_facts", "holder_label"]
