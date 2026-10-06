"""Translate engine item tokens to and from the public PREFIX-N form.

Storage for ``item_dependencies`` is integer ``items.id`` foreign keys.
Engine code that carries an item as its internal id (an int or its digit
string) or as a stored public ref uses :func:`resolve_column_item_ref` on
the way in and :func:`render_column_item_ref` on the way out to the API or
display. A caller's token never arrives here unresolved: it resolves
through :func:`yoke_core.domain.item_ref_resolution.resolve_item_ref`.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.item_ref_render import render_item_refs
from yoke_core.domain.item_ref_resolution import internal_item_key


def resolve_column_item_ref(conn: Any, value: Any) -> Optional[int]:
    """Resolve an engine item token to the internal ``items.id``.

    Returns ``None`` when the token names no item.
    """
    return internal_item_key(conn, value)


def render_column_item_ref(conn: Any, value: Any) -> str:
    """Render the canonical public ref for an engine item token.

    The result always carries the resolved item's own project prefix. A
    token with no backing row renders the same text it arrived with:
    callers feed this result back through :func:`resolve_column_item_ref`,
    so it has to stay a token. Text a person reads names an item through
    :func:`yoke_core.domain.project_identity.render_item_ref`, which says
    plainly that it could not resolve one.
    """
    item_id = resolve_column_item_ref(conn, value)
    if item_id is None:
        return str(value).strip().upper()
    rendered = render_item_refs(conn, [item_id]).get(item_id)
    return rendered or str(value).strip().upper()


__all__ = [
    "render_column_item_ref",
    "resolve_column_item_ref",
]
