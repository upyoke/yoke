"""Generic actor display-name rendering and adoption.

Reading is :func:`actor_display_name`; writing is
:func:`set_actor_display_name`, which adopts a name an external account
system already owns. Both live here because the display surface is one
concern: the name an operator sees for an actor, and where it came from.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.actors import (
    DISPLAY_LABEL_SURFACE,
    GITHUB_LABEL_SURFACE,
    ActorLabelAmbiguous,
    ActorLabelMissing,
    ActorNotFound,
    actor_label,
)


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def actor_display_name(conn: Any, actor_id: int) -> str:
    """Render an actor id to a generic display name.

    Prefer the actor-facing ``display`` surface. Existing installs may only
    have GitHub label rows, so fall back to the system component for system
    actors and then the GitHub label projection. The fallback keeps generic
    actor reads stable without treating ``github_label`` as the data model's
    primary name.
    """
    p = _placeholder(conn)
    actor_row = conn.execute(
        f"SELECT kind, system_component FROM actors WHERE id = {p}",
        (actor_id,),
    ).fetchone()
    if actor_row is None:
        raise ActorNotFound(f"actor id {actor_id} does not exist")
    _, system_component = actor_row

    rows = conn.execute(
        f"SELECT label FROM actor_labels WHERE actor_id = {p} AND surface = {p}",
        (actor_id, DISPLAY_LABEL_SURFACE),
    ).fetchall()
    if len(rows) > 1:
        raise ActorLabelAmbiguous(
            f"actor {actor_id} has {len(rows)} labels on surface "
            f"{DISPLAY_LABEL_SURFACE!r}"
        )
    if rows:
        return str(rows[0][0])
    if system_component is not None:
        return str(system_component)
    try:
        return actor_label(conn, actor_id, surface=GITHUB_LABEL_SURFACE)
    except ActorLabelMissing as exc:
        raise ActorLabelMissing(
            f"actor {actor_id} has no display label, system component, "
            "or GitHub label"
        ) from exc


def set_actor_display_name(
    conn: Any,
    actor_id: int,
    display_name: Any,
) -> bool:
    """Adopt ``display_name`` as the actor's display label; report a change.

    The account system that owns a person's name is the authority for it,
    so this overwrites whatever the display surface currently holds for
    ``actor_id`` — unlike
    :func:`yoke_core.domain.actors.set_actor_label`, which binds a label
    once and leaves a later call as a no-op. A renamed account therefore
    propagates on its next sync instead of pinning the name it first
    signed in under.

    A blank or missing name writes nothing and returns ``False``: an
    account with no name of its own leaves the actor's existing fallback
    chain (system component, then GitHub label) exactly as it was. This
    never invents a name, and it never removes a display row an earlier
    sync established.

    Returns whether the stored label now differs from before, so a caller
    can report an actual rename rather than every sync.
    """
    name = str(display_name or "").strip()
    if not name:
        return False
    p = _placeholder(conn)
    row = conn.execute(
        f"SELECT label FROM actor_labels WHERE actor_id = {p} AND surface = {p}",
        (actor_id, DISPLAY_LABEL_SURFACE),
    ).fetchone()
    if row is not None and str(row[0]) == name:
        return False
    conn.execute(
        "INSERT INTO actor_labels (actor_id, surface, label, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}) "
        "ON CONFLICT (actor_id, surface) DO UPDATE SET label = EXCLUDED.label",
        (
            actor_id,
            DISPLAY_LABEL_SURFACE,
            name,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    return True


__all__ = ["actor_display_name", "set_actor_display_name"]
