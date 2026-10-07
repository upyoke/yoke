"""Public-ref rendering for callers that hold an internal item id.

Item-token *resolution* belongs to
:mod:`yoke_core.domain.item_ref_resolution`; this module renders the other
direction for server-side callers that address an item by ``items.id``.
"""

from __future__ import annotations


from yoke_core.domain.project_identity import render_item_ref, unresolved_item_ref


def item_ref_for_id(item_id: int) -> str:
    """Render ``PREFIX-N`` for an internal id, opening a control-plane read.

    For server-side callers that address an item by ``items.id`` and hold no
    connection of their own (function-call handlers, for instance). Callers
    that already have a connection use
    :func:`yoke_core.domain.project_identity.render_item_ref` directly rather
    than paying for a second one.

    Never raises: many call sites are warning/dry-run notices that must survive
    an unreachable control plane, so an unopenable connection reports the ref
    as unresolved for want of a read rather than inventing one from the id.
    """
    from yoke_core.domain import db_helpers

    try:
        from yoke_contracts.control_plane_locality import (
            RemoteControlPlaneConnectionError,
        )

        with db_helpers.connect() as conn:
            return render_item_ref(conn, int(item_id))
    except RemoteControlPlaneConnectionError:
        # Outside Exception on purpose — https authority has no local DB.
        return unresolved_item_ref(consulted=False)
    except Exception:
        return unresolved_item_ref(consulted=False)


def item_subject_ref(token: int | str) -> str:
    """Name an item from a token that is either an id or a public ref.

    Display callers may hold an owned storage key or a complete public ref.
    Public refs pass through; owned keys are rendered before display. This
    helper does not validate client selectors, which require full public refs.
    """
    text = str(token).strip()
    return item_ref_for_id(int(text)) if text.isdigit() else text


__all__ = [
    "item_ref_for_id",
    "item_subject_ref",
]
