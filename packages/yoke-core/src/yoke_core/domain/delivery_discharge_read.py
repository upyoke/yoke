"""Has this item's delivery actually happened, asked from the merge client.

The answer itself is :mod:`yoke_core.domain.delivery_evidence_ladder`,
resolved server-side because its containment rung needs a connection and the
project's repository comparison source. This is the merge boundary's way in,
so the close-out route and the terminal done guard decide from one fact
rather than two.

Three answers, not two. "Delivered" and "not delivered yet" are both real
readings; a read that could not run is neither, and collapsing it into
"not delivered" is what this whole surface exists to stop doing. Silently
answering no would send an owner back to the release wait with the same
unexplained "missing ceremony nonce" refusal the ladder was built to
eliminate — correct in its caution and useless in its diagnosis. So the
unread case keeps its own state and carries the provider's reason, and the
caller refuses by name instead.

Still fail-closed: unread never asserts the ceremony. It just says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from yoke_contracts.api.function_call import TargetRef

from yoke_core.api.service_client_structured_api_adapter import call_dispatcher


DISCHARGED = "discharged"
NOT_DISCHARGED = "not_discharged"
UNREAD = "unread"


@dataclass(frozen=True)
class DeliveryDischarge:
    """Whether delivery happened, or why that could not be read."""

    state: str
    detail: str = ""
    recovery: str = ""
    # The candidate the release recorded for this item's project, so the
    # close-out can answer containment against it from the lane it stands in.
    release_lineage: str = ""

    @property
    def discharged(self) -> bool:
        return self.state == DISCHARGED

    @property
    def unread(self) -> bool:
        return self.state == UNREAD


def _unread(detail: str) -> DeliveryDischarge:
    return DeliveryDischarge(
        UNREAD,
        detail=detail,
        recovery=(
            "This is an unreadable answer, not a negative one — the item may "
            "well be delivered already. Restore the control-plane read, then "
            "re-run the same close-out command. Do not start another "
            "deployment run to force a verdict: the other members of that "
            "release would then fail the same way."
        ),
    )


def delivery_discharge(
    item: dict[str, Any],
    *,
    dispatch: Callable[..., Any] = call_dispatcher,
) -> DeliveryDischarge:
    """Whether a succeeded run of the item's selected flow delivered it."""
    item_id = item.get("id")
    if item_id is None:
        return _unread("the item carries no id to ask about")
    try:
        response = dispatch(
            function_id="done_transition.delivery_evidence",
            target=TargetRef(kind="item", item_id=int(item_id)),
            payload={},
        )
    except Exception as exc:  # noqa: BLE001 - an unread delivery is not a no
        return _unread(f"the delivery-evidence read failed: {exc}")
    if not getattr(response, "success", False):
        error = getattr(response, "error", None)
        named = getattr(error, "message", None) or error or "no reason reported"
        return _unread(f"the delivery-evidence read was refused: {named}")
    result = getattr(response, "result", None) or {}
    state = str(result.get("state") or "")
    lineage = str(result.get("release_lineage") or "")
    if state == DISCHARGED:
        return DeliveryDischarge(DISCHARGED, release_lineage=lineage)
    if not state:
        return _unread("the delivery-evidence read returned no verdict")
    # The ladder's own "undetermined" is the same unread fact, already
    # carrying the reason and recovery it diagnosed.
    if state == "undetermined":
        return DeliveryDischarge(
            UNREAD,
            detail=str(result.get("reason") or "delivery could not be determined"),
            recovery=str(result.get("recovery") or _unread("").recovery),
        )
    return DeliveryDischarge(
        NOT_DISCHARGED,
        detail=str(result.get("reason") or ""),
        recovery=str(result.get("recovery") or ""),
        release_lineage=lineage,
    )


__all__ = [
    "DISCHARGED",
    "NOT_DISCHARGED",
    "UNREAD",
    "DeliveryDischarge",
    "delivery_discharge",
]
