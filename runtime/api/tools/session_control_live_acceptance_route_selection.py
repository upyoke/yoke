"""The route-selection contract a broker-capable acceptance cell proves.

The plane picks a stopped-session wake route from the target machine's own
relay presence: a machine whose persistent relay is still connected is woken
directly, and a machine without one is woken through a same-machine peer's
one-hop broker. A cell that pins either route is unsatisfiable on the other
kind of machine, so the broker-capable cell asserts the selection instead —
the plane must choose the route the machine's relay presence requires, and
that wake must deliver end to end. Whichever branch the run environment
cannot present records a designed not-exercisable verdict naming the
condition it lacked, never a failure.
"""

from __future__ import annotations

from typing import Any

from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceContractError,
)
from runtime.api.tools.session_control_live_acceptance_wake_route import (
    MACHINE_SELECTED_ROUTE,
    selected_route,
)


RELAY_PRESENT_BRANCH = "machine_relay_fresh"
RELAY_ABSENT_BRANCH = "machine_relay_absent"


def machine_relay_fresh(row: dict[str, Any], *, cell: AcceptanceCell) -> bool:
    """Read the same machine relay-presence window the plane routes wakes by."""
    routing = row.get("messageability")
    fresh = routing.get("relay_connected") if isinstance(routing, dict) else None
    if not isinstance(fresh, bool):
        raise AcceptanceContractError(
            "machine_relay_presence_unreadable", surface=cell.surface
        )
    return fresh


def broker_hop_carries_wake(row: dict[str, Any], *, cell: AcceptanceCell) -> bool:
    """True when a peer's one-hop broker, not a machine relay, must wake this cell.

    Roster wake availability is derived from the machine relay, and the plane
    recruits a broker peer exactly when that relay is absent. An unavailable
    machine route is therefore the expected shape for a route-selection cell
    on a relay-less machine, not a precondition failure.
    """
    return cell.route == MACHINE_SELECTED_ROUTE and not machine_relay_fresh(
        row, cell=cell
    )


def resolve_route_selection(
    row: dict[str, Any], *, cell: AcceptanceCell
) -> tuple[str, dict[str, Any] | None]:
    """Return the route this cell's wake must take and the verdict to record.

    Only a broker-capable cell selects; every other cell already carries the
    single route its matrix entry authored, and records no branch verdict.
    """
    if cell.route != MACHINE_SELECTED_ROUTE:
        return cell.route, None
    relay_fresh = machine_relay_fresh(row, cell=cell)
    route = selected_route(relay_fresh=relay_fresh)
    exercised = RELAY_PRESENT_BRANCH if relay_fresh else RELAY_ABSENT_BRANCH
    unexercised = RELAY_ABSENT_BRANCH if relay_fresh else RELAY_PRESENT_BRANCH
    return route, {
        "contract": "machine_relay_presence_selects_wake_route",
        "machine_relay_fresh": relay_fresh,
        "selected_route": route,
        "exercised_branch": exercised,
        "unexercised_branch": unexercised,
        "unexercised_verdict": "designed_not_exercisable",
        "unexercised_condition": exercised,
    }


__all__ = [
    "RELAY_ABSENT_BRANCH",
    "RELAY_PRESENT_BRANCH",
    "broker_hop_carries_wake",
    "machine_relay_fresh",
    "resolve_route_selection",
]
