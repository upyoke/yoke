"""Owner-facing native session-control version gates."""

from typing import Mapping

from yoke_contracts.session_control.surface_versions import (
    surface_operation_supported,
)


_WAKE_OPERATION_BY_LIVENESS = {
    "active": "message_active",
    "stale": "message_idle",
    "ended": "message_stopped",
}


def wake_versions_supported(
    surface: str,
    target_version: str | None,
    relay_version: str | None,
    liveness: str,
) -> bool:
    operation = _WAKE_OPERATION_BY_LIVENESS.get(liveness)
    return bool(
        operation
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
        str(candidate.get("liveness") or ""),
    )


__all__ = [
    "surface_operation_supported",
    "wake_candidate_supported",
    "wake_versions_supported",
]
