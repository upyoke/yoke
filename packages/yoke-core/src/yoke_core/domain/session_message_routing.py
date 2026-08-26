"""Session liveness and capability-derived message routing facts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from yoke_contracts.session_control.capabilities import capability_for_surface
from yoke_contracts.session_control.surface_versions import (
    machine_wake_surface,
    surface_operation_supported,
    surface_version_supported,
)
from yoke_contracts.session_control.liveness import LIVENESS_TERMINATED
from yoke_core.domain.session_staleness import activity_is_stale
from yoke_core.domain.session_message_types import parse_timestamp


def latest_hook_activity(row: dict[str, Any]) -> datetime | None:
    candidates = [
        parse_timestamp(row.get("last_tool_call_at")),
        parse_timestamp(row.get("last_injected_at")),
    ]
    present = [value for value in candidates if value is not None]
    return max(present) if present else None


def latest_observed_activity(row: dict[str, Any]) -> datetime | None:
    candidates = [
        latest_hook_activity(row),
        parse_timestamp(row.get("last_heartbeat")),
    ]
    present = [value for value in candidates if value is not None]
    return max(present) if present else None


def session_liveness(row: dict[str, Any], *, now: datetime) -> str:
    if row.get("terminated_at"):
        return LIVENESS_TERMINATED
    if row.get("ended_at"):
        return "ended"
    raw_activity = max(
        str(row.get("last_heartbeat") or ""),
        str(row.get("last_tool_call_at") or ""),
    )
    if activity_is_stale(raw_activity, executor=row.get("executor"), now=now):
        return "stale"
    return "active"


_WAKE_OPERATION_BY_LIVENESS = {
    "active": "message_active",
    "stale": "message_idle",
    "ended": "message_stopped",
}


def _wake_operation(row: dict[str, Any], liveness: str) -> str | None:
    if row.get("turn_posture") == "waiting":
        return "message_stopped"
    return _WAKE_OPERATION_BY_LIVENESS.get(liveness)


def _wake_interface(
    surface: str,
    version: str | None,
    operation: str | None,
    machine_surface_versions: Mapping[str, str] | None,
) -> str:
    capability = capability_for_surface(surface)
    if capability is None or operation is None:
        return "none"
    if surface_operation_supported(surface, version, operation):
        return str(getattr(capability, operation))
    if (
        operation
        and machine_wake_surface(surface, machine_surface_versions, operation)
        is not None
    ):
        return "supported"
    return "none"


def messageability(
    row: dict[str, Any],
    *,
    liveness: str,
    machine_surface_versions: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Project hook delivery and wake facts for one session.

    Hook delivery follows the session's own registered surface and version.
    A stopped session may still be wakeable through a peer binary installed on
    its machine, so the caller passes the relay-reported installed versions and
    the wake route is derived from those rather than from the registered
    surface alone.
    """
    if liveness == LIVENESS_TERMINATED:
        return {
            "messageable": False,
            "hook_injection": False,
            "wake_interface": "none",
            "reason": "session_terminated",
        }
    surface = str(row.get("executor_surface") or "")
    capability = capability_for_surface(surface)
    if capability is None:
        return {
            "messageable": False,
            "hook_injection": False,
            "wake_interface": "none",
            "reason": "unknown_surface",
        }
    version = str(row.get("executor_version") or "") or None
    operation = _wake_operation(row, liveness)
    wake_interface = _wake_interface(
        surface, version, operation, machine_surface_versions
    )
    if not surface_version_supported(surface, version):
        return {
            "messageable": False,
            "hook_injection": False,
            "wake_interface": wake_interface,
            "wake_operation": operation,
            "reason": "version_below_floor_or_unknown",
            "minimum_version": capability.minimum_version,
        }
    hook_injection = bool(capability.inject_events)
    return {
        "messageable": hook_injection,
        "hook_injection": hook_injection,
        "inject_events": list(capability.inject_events),
        "wake_interface": wake_interface,
        "wake_operation": operation,
        "minimum_version": capability.minimum_version,
        "reason": "hook_delivery" if hook_injection else "unsupported_surface",
    }


__all__ = [
    "latest_hook_activity",
    "latest_observed_activity",
    "messageability",
    "session_liveness",
]
