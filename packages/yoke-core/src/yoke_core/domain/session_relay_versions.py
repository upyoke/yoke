"""Owner-facing native session-control version gates."""

from typing import Mapping

from yoke_contracts.session_control.surface_versions import (
    surface_operation_supported,
)
from yoke_core.domain.session_relay_types import WakeMode


_WAKE_OPERATION_BY_LIVENESS = {
    "active": "message_active",
    "stale": "message_idle",
    "ended": "message_stopped",
}


def wake_versions_supported(
    surface: str,
    target_version: str | None,
    relay_version: str | None,
    wake_mode: str,
    liveness: str,
) -> bool:
    try:
        mode = WakeMode(wake_mode)
    except ValueError:
        return False
    operation = (
        "message_stopped"
        if mode is WakeMode.WAITING
        else _WAKE_OPERATION_BY_LIVENESS.get(liveness)
    )
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
        str(candidate.get("wake_mode") or ""),
        str(candidate.get("liveness") or ""),
    )


__all__ = [
    "surface_operation_supported",
    "wake_candidate_supported",
    "wake_versions_supported",
]
