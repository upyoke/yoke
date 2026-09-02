"""Owner-facing native session-control version gates."""

from typing import Mapping

from yoke_contracts.session_control.capabilities import native_wake_supported
from yoke_contracts.session_control.surface_versions import (
    machine_wake_surface,
    surface_operation_supported,
)
from yoke_core.domain.session_relay_types import WakeMode


_WAKE_OPERATION_BY_LIVENESS = {
    "active": "message_active",
    "stale": "message_idle",
    "ended": "message_stopped",
}


def wake_operation(wake_mode: str, liveness: str) -> str | None:
    try:
        mode = WakeMode(wake_mode)
    except ValueError:
        return None
    return (
        "message_stopped"
        if mode is WakeMode.WAITING
        else _WAKE_OPERATION_BY_LIVENESS.get(liveness)
    )


def wake_versions_supported(
    surface: str,
    target_version: str | None,
    relay_version: str | None,
    wake_mode: str,
    liveness: str,
) -> bool:
    operation = wake_operation(wake_mode, liveness)
    return bool(
        operation
        and native_wake_supported(surface)
        and surface_operation_supported(surface, target_version, operation)
        and surface_operation_supported(surface, relay_version, operation)
    )


def wake_candidate_supported(
    candidate: Mapping[str, object],
    relay_versions: Mapping[str, str],
) -> bool:
    surface = str(candidate.get("executor_surface") or "")
    return wake_versions_supported(
        surface,
        str(candidate.get("executor_version") or ""),
        relay_versions.get(surface),
        str(candidate.get("wake_mode") or ""),
        str(candidate.get("liveness") or ""),
    )


def wake_execution_surface(
    candidate: Mapping[str, object],
    relay_versions: Mapping[str, str],
) -> tuple[str, str] | None:
    """Return the surface and version of the binary that performs one wake.

    A session whose own surface proves the operation is resumed by that surface.
    A stopped Claude session registered under an app with no resume route is
    resumed by the CLI the same machine reports, so the route is only available
    when that peer binary qualifies — and it, not the registered surface, is
    what the relay must be handed to execute the wake.
    """
    surface = str(candidate.get("executor_surface") or "")
    if wake_candidate_supported(candidate, relay_versions):
        return surface, str(relay_versions.get(surface) or "")
    operation = wake_operation(
        str(candidate.get("wake_mode") or ""),
        str(candidate.get("liveness") or ""),
    )
    if operation is None:
        return None
    return machine_wake_surface(surface, relay_versions, operation)


__all__ = [
    "surface_operation_supported",
    "wake_candidate_supported",
    "wake_execution_surface",
    "wake_operation",
    "wake_versions_supported",
]
