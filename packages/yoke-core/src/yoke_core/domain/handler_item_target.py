"""The item a handler acts on, read from its dispatcher-resolved target.

Claim and permission checks run against ``target.item_id``, which the
dispatcher resolved from the caller's public ref. A payload ``item_id``
that also names the item must agree with it; a payload may supply the item
alone only when the target carries none.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.api.function_call import FunctionCallRequest


def request_item_id(request: FunctionCallRequest, payload_item_id: Any = None) -> int:
    """Return the internal id of the item ``request`` addresses.

    Raises ``ValueError`` naming the fix when the payload disagrees with the
    target or neither names an item.
    """
    target_item_id = request.target.item_id
    if target_item_id is not None:
        if payload_item_id is not None and int(payload_item_id) != int(target_item_id):
            raise ValueError(
                "payload names a different item than the target; address the "
                "item by target.public_ref (PREFIX-N) alone"
            )
        return int(target_item_id)
    if payload_item_id is not None:
        return int(payload_item_id)
    raise ValueError("an item target is required: pass target.public_ref (PREFIX-N)")


__all__ = ["request_item_id"]
