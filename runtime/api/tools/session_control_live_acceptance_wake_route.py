"""Wake-route expectation derived from a machine's installed surfaces."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_contracts.session_control.surface_versions import (
    machine_stopped_wake_supported,
    surface_operation_supported,
)


MACHINE_SELECTED_ROUTE = "machine_selected"


def expected_wake_route(
    surface: str,
    expected_version: str,
    machine_versions: Mapping[str, str],
) -> str:
    """Return the wake route a surface has on the machine the matrix describes.

    A surface is reachable either through its own proven stopped-wake route or
    through a peer binary the same machine has installed, so the expectation
    follows the declared installed versions rather than the surface alone.
    The matrix builder and the matrix contract both read it, so a built
    document always satisfies the contract it is checked against.
    """
    return (
        "direct"
        if surface_operation_supported(surface, expected_version, "message_stopped")
        or machine_stopped_wake_supported(surface, machine_versions)
        else "none"
    )


def surface_route_mismatch(cells: Sequence[Any]) -> Any | None:
    """Return the first surface cell whose authored route contradicts its machine.

    A candidate subset is exempt: selection removes the installed versions its
    surviving cells would then be judged against.
    """
    surfaces = [cell for cell in cells if cell.acceptance_role == "surface"]
    machine_versions = {cell.surface: cell.expected_version for cell in surfaces}
    return next(
        (
            cell
            for cell in surfaces
            if cell.wake_route
            != expected_wake_route(
                cell.surface, cell.expected_version, machine_versions
            )
        ),
        None,
    )


def selected_route(*, relay_fresh: bool) -> str:
    """Return the route the plane must choose for one machine's relay presence.

    A machine whose persistent relay is still connected carries the wake
    itself, and the plane declines to recruit a peer for it; a machine without
    one is reachable only through a same-machine peer's one-hop broker. The
    route is therefore a property of the machine at wake time, never one a
    matrix cell can pin in advance.
    """
    return "direct" if relay_fresh else "broker"


__all__ = [
    "MACHINE_SELECTED_ROUTE",
    "expected_wake_route",
    "selected_route",
    "surface_route_mismatch",
]
