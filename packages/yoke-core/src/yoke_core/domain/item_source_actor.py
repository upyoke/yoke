"""Resolve and validate the actor attributed to a newly created item.

Session-bound creation reads ``harness_sessions.actor_id``. A genuine
plain-terminal call has no session, so it resolves the universe's operating
human instead. Explicit source and owner values remain numeric actor ids.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.actors import validate_actor_id


class ItemSourceActorResolutionError(Exception):
    """Raised when item creation cannot resolve a valid actor id."""


def resolve_item_source_actor(conn: Any, session_id: Optional[str]) -> int:
    """Resolve an item's source from a session or terminal operator."""
    if not session_id:
        from yoke_core.domain.session_actor_binding import resolve_operating_actor

        binding = resolve_operating_actor(conn)
        if binding.actor_id is not None:
            return binding.actor_id
        raise ItemSourceActorResolutionError(
            f"{binding.code}: cannot resolve a source actor for the new item. "
            f"{binding.detail}"
        )

    from yoke_core.domain.path_claims_actor_resolution import (
        ActorResolutionUnavailable,
        resolve_actor_for_caller,
    )

    try:
        return resolve_actor_for_caller(conn, None, session_id=session_id)
    except ActorResolutionUnavailable as exc:
        raise ItemSourceActorResolutionError(
            f"cannot resolve a source actor for the new item: {exc}. "
            "Pass an explicit numeric --source actor id or create the "
            "item from a registered harness session."
        ) from exc


def coerce_explicit_item_source(conn: Any, source: str) -> int:
    """Validate an operator-supplied source or owner as an actor id."""
    try:
        actor_id = int(source.strip())
    except ValueError as exc:
        raise ItemSourceActorResolutionError(
            f"items.source must be a numeric actor id, got {source!r}; "
            "mechanism labels are no longer accepted on the write path"
        ) from exc
    if not validate_actor_id(conn, actor_id):
        raise ItemSourceActorResolutionError(
            f"items.source={actor_id} does not match any actors row"
        )
    return actor_id


__all__ = [
    "ItemSourceActorResolutionError",
    "coerce_explicit_item_source",
    "resolve_item_source_actor",
]
