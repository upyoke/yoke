"""Bind a relay worker's HTTPS calls to its attested launch actor."""

from __future__ import annotations

from typing import Any

from yoke_core.api.http_auth import HttpAuthContext, bind_actor_from_auth
from yoke_core.domain.session_ownership import delegated_launch_actor


def session_actor_for(
    auth: HttpAuthContext, session_id: str, *, conn: Any = None
) -> int:
    """Use the credential's actor unless its exact live launch delegates it."""
    if not session_id or not auth.machine_id:
        return auth.actor_id
    delegated_actor = delegated_launch_actor(
        session_id=session_id,
        machine_id=auth.machine_id,
        token_actor_id=auth.actor_id,
        conn=conn,
    )
    return auth.actor_id if delegated_actor is None else delegated_actor


def bind_actor_for_session(
    envelope: dict[str, Any], auth: HttpAuthContext
) -> tuple[dict[str, Any], str | None]:
    """Use the token actor except for its exact attested relay launch.

    The client-supplied actor is always discarded. The dispatcher still
    checks the resulting actor against ``harness_sessions`` and applies the
    registered function's ordinary claim and permission gates.
    """
    bound, session_id = bind_actor_from_auth(envelope, auth)
    actor_id = session_actor_for(auth, session_id or "")
    if actor_id != auth.actor_id:
        bound["actor"]["actor_id"] = str(actor_id)
    return bound, session_id


__all__ = ["bind_actor_for_session", "session_actor_for"]
