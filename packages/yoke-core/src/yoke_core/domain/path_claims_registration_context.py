"""Item, project, and actor context for path-claim registration."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.path_claims_actor_resolution import (
    ActorResolutionUnavailable,
    resolve_actor_for_caller,
)


class PathClaimRegistrationError(Exception):
    """Base class for item-facing registration context failures."""


class ItemNotFound(PathClaimRegistrationError):
    """The item id does not exist."""


class ItemHasNoProject(PathClaimRegistrationError):
    """The item exists but has no project identity."""


class DefaultActorUnavailable(PathClaimRegistrationError):
    """No explicit or writer-default actor could be resolved."""


def parameter_marker(conn: Any) -> str:
    """Return the connection's SQL parameter marker."""
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def fetch_item_project_id(conn: Any, item_id: int) -> int:
    """Resolve the canonical project id for an item."""
    marker = parameter_marker(conn)
    row = conn.execute(
        f"SELECT project_id FROM items WHERE id = {marker}",
        (item_id,),
    ).fetchone()
    if row is None:
        raise ItemNotFound(f"item id {item_id} does not exist")
    project_id = row[0] if not hasattr(row, "keys") else row["project_id"]
    if not project_id:
        raise ItemHasNoProject(
            f"item {item_id} has no project_id; cannot resolve canonical paths"
        )
    return int(project_id)


def resolve_registration_actor(
    conn: Any,
    explicit_actor_id: Optional[int],
    *,
    session_id: Optional[str] = None,
) -> int:
    """Honour an explicit actor or use the writer-default actor."""
    try:
        return resolve_actor_for_caller(
            conn,
            explicit_actor_id,
            session_id=session_id,
        )
    except ActorResolutionUnavailable as exc:
        raise DefaultActorUnavailable(str(exc)) from exc


__all__ = [
    "DefaultActorUnavailable",
    "ItemHasNoProject",
    "ItemNotFound",
    "PathClaimRegistrationError",
    "fetch_item_project_id",
    "parameter_marker",
    "resolve_registration_actor",
]
