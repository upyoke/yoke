"""Generic actor display-name rendering."""

from __future__ import annotations

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


__all__ = ["actor_display_name"]
