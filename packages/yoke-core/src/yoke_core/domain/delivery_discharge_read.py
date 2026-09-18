"""Has this item's delivery actually happened, asked from the merge client.

The answer itself is :mod:`yoke_core.domain.delivery_evidence_ladder`,
resolved server-side because its containment rung needs a connection and the
project's repository comparison source. This is the merge boundary's way in,
so the close-out route and the terminal done guard decide from one fact
rather than two.

Fail-closed on purpose. A read that could not run answers ``False``, which
leaves the item at its release wait exactly as it was — the same outcome as
before this read existed. Answering ``True`` on an unread delivery would
assert a ceremony nobody performed.
"""

from __future__ import annotations

from typing import Any, Callable

from yoke_contracts.api.function_call import TargetRef

from yoke_core.api.service_client_structured_api_adapter import call_dispatcher


DISCHARGED = "discharged"


def delivery_has_discharged(
    item: dict[str, Any],
    *,
    dispatch: Callable[..., Any] = call_dispatcher,
) -> bool:
    """Whether a succeeded run of the item's selected flow delivered it."""
    item_id = item.get("id")
    if item_id is None:
        return False
    try:
        response = dispatch(
            function_id="done_transition.delivery_evidence",
            target=TargetRef(kind="item", item_id=int(item_id)),
            payload={},
        )
    except Exception:  # noqa: BLE001 - an unread delivery is not a discharge
        return False
    if not getattr(response, "success", False):
        return False
    result = getattr(response, "result", None) or {}
    return str(result.get("state") or "") == DISCHARGED


__all__ = ["delivery_has_discharged"]
