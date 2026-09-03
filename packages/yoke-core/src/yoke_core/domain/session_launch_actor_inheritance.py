"""Bind a launched session's actor to the actor that requested the launch.

Authority follows the person, not the machine. A session a person opens
signs in as itself; a session another session *launched* acts for whoever
started that chain, however many machines it crossed. The launch row
already names that actor — ``session_launches.requester_actor_id`` is the
dispatcher-resolved actor of the calling session, never a caller
assertion — so inheritance is a read of the launch the registering
session was started by, and it is transitive for free: a session that
launches another passes on the actor it inherited.

Why the read has to happen at registration rather than afterwards: the
alternative resolution
(:func:`yoke_core.domain.session_actor_binding.resolve_operating_actor`)
answers "who operates *this machine*", which for a launched worker is the
wrong person — the machine's own login on a local universe, the relay's
bearer-token owner on a hosted one. Binding that first and correcting it
later would leave the launched session's own start event attributed to
the machine.

A launch id that names no readable row is a refusal rather than a
fallback, for the same reason: silently binding the machine's operating
actor is exactly the misattribution this module exists to prevent.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.session_actor_binding import ActorBinding


#: Refusal code. Uppercase to match the other session-registration codes,
#: which operators and the function dispatcher both read.
LAUNCH_ACTOR_UNRESOLVED = "SESSION_LAUNCH_ACTOR_UNRESOLVED"

_RECOVERY = (
    "Recovery: confirm the launch exists (`yoke session-control launch get "
    "<launch-id>`); a session started outside a launch must register without "
    "a launch id so it binds its own sign-in identity instead."
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _unresolved(launch_id: str, cause: str) -> ActorBinding:
    return ActorBinding(
        code=LAUNCH_ACTOR_UNRESOLVED,
        detail=(
            f"launch {launch_id!r} {cause}, so the launched session has no "
            f"actor to inherit and must not fall back to the operating actor "
            f"of the machine running it. {_RECOVERY}"
        ),
    )


def resolve_launch_requester_actor(conn: Any, launch_id: str) -> ActorBinding:
    """Return the actor that requested ``launch_id``, or a named refusal."""
    identifier = str(launch_id or "").strip()
    if not identifier:
        return _unresolved("", "is empty")
    try:
        row = conn.execute(
            "SELECT requester_actor_id FROM session_launches "
            f"WHERE launch_id = {_p(conn)}",
            (identifier,),
        ).fetchone()
    except db_backend.operational_error_types(conn):
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001 — the probe result is the product
            pass
        return _unresolved(identifier, "could not be read on this control plane")
    if row is None:
        return _unresolved(identifier, "is not registered on this control plane")
    raw = row.get("requester_actor_id") if hasattr(row, "get") else row[0]
    try:
        return ActorBinding(actor_id=int(raw))
    except (TypeError, ValueError):
        return _unresolved(identifier, "names no requesting actor")


__all__ = ["LAUNCH_ACTOR_UNRESOLVED", "resolve_launch_requester_actor"]
