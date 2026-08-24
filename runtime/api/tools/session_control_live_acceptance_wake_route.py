"""Wake-route expectation derived from a machine's installed surfaces."""

from __future__ import annotations

from typing import Mapping

from yoke_contracts.session_control.surface_versions import (
    machine_stopped_wake_supported,
    surface_operation_supported,
)


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


__all__ = ["expected_wake_route"]
