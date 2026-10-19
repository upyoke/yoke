"""Render an item's owner as the actor's name plus its actor id.

``items.owner`` stores an ``actors.id`` as text. Every read that shows an
owner to a person emits three facts from this module: ``owner_actor_id``,
``owner_name`` and ``owner_label``. The label is the one rendered form:

- ``Ben Bauman (actor id: 2)`` for a resolved actor;
- ``unknown actor (actor id: 9)`` when no named actor row answers the id;
- ``unknown actor (stored owner: ben)`` for non-numeric stored text;
- ``unassigned`` when no owner is stored.
"""

from __future__ import annotations

from typing import Any, Iterable

UNASSIGNED_OWNER_LABEL = "unassigned"
_UNSET_OWNER_TOKENS = frozenset({"", "none", "null"})


def stored_owner_text(value: Any) -> str:
    """Normalize a stored owner cell; unset tokens become ``""``."""
    text = "" if value is None else str(value).strip()
    return "" if text.lower() in _UNSET_OWNER_TOKENS else text


def owner_actor_id(value: Any) -> int | None:
    """Return the actor id a stored owner names, or ``None``."""
    text = stored_owner_text(value)
    return int(text) if text.isdigit() else None


def owner_label(stored: Any, name: str | None) -> str:
    """Compose the rendered owner form from the stored value and name."""
    text = stored_owner_text(stored)
    if not text:
        return UNASSIGNED_OWNER_LABEL
    actor_id = owner_actor_id(text)
    if actor_id is None:
        return f"unknown actor (stored owner: {text})"
    return f"{name or 'unknown actor'} (actor id: {actor_id})"


def resolve_owner_names(conn: Any, stored_values: Iterable[Any]) -> dict[int, str]:
    """Resolve each distinct owner actor id once; unknown ids are omitted."""
    from yoke_core.domain.actors import ActorError, actor_name

    names: dict[int, str] = {}
    actor_ids = {owner_actor_id(value) for value in stored_values}
    for actor_id in sorted(i for i in actor_ids if i is not None):
        try:
            name = actor_name(conn, actor_id)
        except ActorError:
            continue
        if name:
            names[actor_id] = name
    return names


def owner_facts(stored: Any, names: dict[int, str]) -> dict[str, Any]:
    """Return the owner fields a read response carries for one item."""
    actor_id = owner_actor_id(stored)
    name = names.get(actor_id) if actor_id is not None else None
    return {
        "owner_actor_id": actor_id,
        "owner_name": name,
        "owner_label": owner_label(stored, name),
    }


__all__ = [
    "UNASSIGNED_OWNER_LABEL",
    "owner_actor_id",
    "owner_facts",
    "owner_label",
    "resolve_owner_names",
    "stored_owner_text",
]
