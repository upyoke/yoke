"""CLI/API item-reference resolution at the public identity boundary.

Splits the higher-level resolver surface out of ``project_identity`` (which
owns the storage-level primitives ``resolve_item_id`` / ``resolve_project``).
This module retains the invocation adapter used by older direct CLI paths but
delegates token interpretation to :mod:`yoke_core.domain.yok_n_parser`.
"""

from __future__ import annotations

from typing import Any, Optional, Union

from yoke_core.domain.yok_n_parser import parse_item_argument


def resolve_cli_item_ref(
    conn: Any,
    raw: str | int,
    *,
    project_context: Optional[Union[str, int]] = None,
) -> int:
    """Resolve a CLI/API item token to the internal ``items.id``.

    Token shapes:
    - ``PREFIX-seq`` -> by public prefix (self-describing)
    - bare ``seq``   -> sequence within explicit or mapped-checkout context
    A real ``int`` is an already-resolved internal row id (passthrough); that
    path is for internal callers, never the string boundary.
    """
    return parse_item_argument(raw, project=project_context, conn=conn)


def item_ref_for_id(item_id: int) -> str:
    """Render ``PREFIX-N`` for an internal id, opening a control-plane read.

    For server-side callers that address an item by ``items.id`` and hold no
    connection of their own (function-call handlers, for instance). Callers
    that already have a connection use
    :func:`yoke_core.domain.project_identity.render_item_ref` directly rather
    than paying for a second one.

    Never raises: many call sites are warning/dry-run notices that must survive
    an unreachable control plane, so an unopenable connection degrades to the
    default-prefix form the renderer itself falls back to.
    """
    from yoke_core.domain import db_helpers
    from yoke_core.domain.project_identity import (
        DEFAULT_PUBLIC_ITEM_PREFIX,
        render_item_ref,
    )

    try:
        from yoke_contracts.control_plane_locality import (
            RemoteControlPlaneConnectionError,
        )

        with db_helpers.connect() as conn:
            return render_item_ref(conn, int(item_id))
    except RemoteControlPlaneConnectionError:
        # Outside Exception on purpose — https authority has no local DB.
        return f"{DEFAULT_PUBLIC_ITEM_PREFIX}-{int(item_id)}"
    except Exception:
        return f"{DEFAULT_PUBLIC_ITEM_PREFIX}-{int(item_id)}"


__all__ = [
    "item_ref_for_id",
    "resolve_cli_item_ref",
]
