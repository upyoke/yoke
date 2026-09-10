"""Resolve the one human actor the local UI server may act as.

The loopback UI admits a per-run session token, not a person, so
actor-scoped writes (Overview module dismissals) need a server-side
answer to "which human is this machine's operator?". That is the same
question session registration asks, so both read one resolver —
:func:`yoke_core.domain.session_actor_binding.resolve_operating_actor`:
one human actor in the universe wins; among several, the one labeled
with the server process's OS login; anything else resolves to nobody.

The UI treats "nobody" as a missing capability rather than an error: it
hides the dismissal controls (``dismiss_available`` false) while module
facts keep rendering.
"""

from __future__ import annotations

from typing import Optional


def resolve_local_operator_actor() -> Optional[int]:
    """Return the local operator's ``actors.id``, or ``None`` when unresolved."""
    from yoke_core.domain import db_helpers
    from yoke_core.domain.session_actor_binding import resolve_operating_actor

    conn = db_helpers.connect()
    try:
        return resolve_operating_actor(conn).actor_id
    finally:
        conn.close()


__all__ = ["resolve_local_operator_actor"]
