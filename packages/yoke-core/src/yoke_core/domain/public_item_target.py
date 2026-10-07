"""Serialize an engine item identity onto a public control-plane target."""

from __future__ import annotations

from typing import Any

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.public_ref import parse_public_item_ref


_REFUSAL = (
    "public_item_ref_required: an internal item key cannot leave the engine. "
    "Pass the item's public ref (PREFIX-N) through the client call chain."
)


def public_item_target(item: Any, *, kind: str = "item", **fields: Any) -> TargetRef:
    """Use a public ref, or render a local join key before it leaves the engine.

    A numeric key is usable only when this process owns a local connection.
    HTTPS callers keep their public ref throughout orchestration instead.
    """
    prefix, sequence = parse_public_item_ref(str(item))
    if prefix is not None and sequence is not None:
        return TargetRef(kind=kind, public_ref=str(item), **fields)
    if not isinstance(item, int) or isinstance(item, bool) or item < 1:
        raise ValueError(_REFUSAL)
    from yoke_core.domain.control_plane_transport import local_connection_or_none
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.item_ref_render import render_item_refs

    conn = local_connection_or_none(connect)
    if conn is not None:
        try:
            refs = render_item_refs(conn, [item])
        finally:
            conn.close()
        ref = refs.get(int(item))
        if ref:
            return TargetRef(kind=kind, public_ref=ref, **fields)
    raise ValueError(_REFUSAL)
