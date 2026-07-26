"""Resolve the one human actor the local UI server may act as.

The loopback UI admits a per-run session token, not a person, so
actor-scoped writes (Overview module dismissals) need a server-side
answer to "which human is this machine's operator?". Resolution is
deliberately narrow and fail-closed:

* exactly one human actor in the universe — that actor;
* several humans — the single human whose ``actor_labels`` row matches
  the server process's OS login (the label the local-universe birth path
  seeds for the machine owner);
* no humans, no login match, or an ambiguous match — nobody. The UI
  then hides the dismissal controls (``dismiss_available`` false) while
  module facts keep rendering.
"""

from __future__ import annotations

import getpass
from typing import Optional


def _os_login() -> str:
    try:
        return (getpass.getuser() or "").strip()
    except Exception:
        return ""


def resolve_local_operator_actor() -> Optional[int]:
    """Return the local operator's ``actors.id``, or ``None`` when unresolved."""
    from yoke_core.domain import db_helpers

    conn = db_helpers.connect()
    try:
        humans = [
            int(row[0])
            for row in conn.execute(
                "SELECT id FROM actors WHERE kind = 'human' ORDER BY id"
            ).fetchall()
        ]
        if not humans:
            return None
        if len(humans) == 1:
            return humans[0]
        login = _os_login()
        if not login:
            return None
        matches = [
            int(row[0])
            for row in conn.execute(
                "SELECT DISTINCT al.actor_id FROM actor_labels al "
                "JOIN actors a ON a.id = al.actor_id "
                "WHERE a.kind = 'human' AND al.label = %s",
                (login,),
            ).fetchall()
        ]
        return matches[0] if len(matches) == 1 else None
    finally:
        conn.close()


__all__ = ["resolve_local_operator_actor"]
