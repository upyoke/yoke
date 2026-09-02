"""Resolve and validate the actor attributed to a newly created item.

The dispatcher's identity binder resolves the actor before the handler
runs — from the session when there is one, and from the universe's
operating human when there is not
(:mod:`yoke_core.domain.session_less_actor_binding`) — so a bound
envelope already carries it and creation reads it straight off the
request.

What is left here is the refusal. A universe that cannot name its
operating actor at all (no human seeded, or several with none matching
this machine's login) reaches creation with nothing bound, and the
recovery belongs to that resolution rather than to item creation, so the
named binding refusal is what this raises. Explicit source and owner
values remain numeric actor ids.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.actors import validate_actor_id


class ItemSourceActorResolutionError(Exception):
    """Raised when item creation cannot resolve a valid actor id."""


def resolve_item_source_actor(conn: Any, session_id: Optional[str]) -> int:
    """Resolve an item's source from a session or terminal operator.

    Reached only when the envelope carried no actor id: on the terminal
    path that means the operating-actor resolution the binder already
    attempted found nothing, and its refusal names the recovery.
    """
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
