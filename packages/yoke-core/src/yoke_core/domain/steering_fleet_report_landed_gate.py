"""What a landed item's own done gate still waits on.

A landed row is classified from the facts the done gate itself reads, never
from whoever happens to hold the item. The delivery-evidence ladder is
satisfied by a succeeded completion run, an independently delivered final
member, or — when the item has no deployment target — the merge alone. A
landing with none of those, whose flow targets a real tier, is waiting on
that flow's next release and owes nobody a command.

Classifying by holder posture instead sent seats to wake an unparked holder
on an item that was simply waiting for the next deployment run, exactly like
the parked rows the same report listed as healthy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from yoke_core.domain.gate_satisfier_facts import Fact, FactVerdict
from yoke_core.domain.gate_satisfier_item_facts import (
    ITEM_DEPLOYMENT_RUN_SUCCEEDED,
    ITEM_INDEPENDENT_MEMBER_DELIVERED,
    ITEM_NO_DEPLOYMENT_TARGET,
)

#: The flow targets a real tier and no delivery fact is present yet.
AWAITING_RELEASE = "awaiting_release"
#: The item has no deployment target, so its merge is the delivery.
CLOSE_OUT_READY = "close_out_ready"
#: A completion run or independent member delivery is recorded.
DELIVERED = "delivered"
#: A fact the classification needs could not be read.
UNREADABLE = "unreadable"


@dataclass(frozen=True)
class LandedGate:
    """One landed item's delivery-gate state, with the flow it waits on."""

    state: str
    #: The effective deployment flow, when the facts name one.
    flow: str = ""
    #: The unreadable fact's own explanation; empty otherwise.
    detail: str = ""


def landed_gate(facts: Mapping[str, Fact]) -> LandedGate:
    """Classify a merged item from its delivery-evidence facts."""
    target = facts[ITEM_NO_DEPLOYMENT_TARGET]
    delivery = (
        facts[ITEM_DEPLOYMENT_RUN_SUCCEEDED],
        facts[ITEM_INDEPENDENT_MEMBER_DELIVERED],
    )
    if any(fact.verdict == FactVerdict.PRESENT for fact in delivery):
        return LandedGate(DELIVERED, flow=target.value)
    if target.verdict == FactVerdict.PRESENT:
        return LandedGate(CLOSE_OUT_READY, flow=target.value)
    for fact in (target, *delivery):
        if fact.verdict == FactVerdict.UNKNOWN:
            return LandedGate(UNREADABLE, flow=target.value, detail=fact.detail)
    return LandedGate(AWAITING_RELEASE, flow=target.value)


__all__ = [
    "AWAITING_RELEASE",
    "CLOSE_OUT_READY",
    "DELIVERED",
    "UNREADABLE",
    "LandedGate",
    "landed_gate",
]
