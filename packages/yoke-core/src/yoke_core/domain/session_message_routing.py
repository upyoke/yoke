"""Session liveness and capability-derived message routing facts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from yoke_contracts.session_control.capabilities import (
    capability_for_surface,
    native_wake_supported,
    surface_wake_authority,
)
from yoke_contracts.session_control.surface_versions import (
    machine_wake_surface,
    surface_operation_supported,
    surface_version_supported,
)
from yoke_core.domain.session_message_types import parse_timestamp
from yoke_core.domain.session_relay_versions import wake_operation


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


def _wake_interface(
    surface: str,
    version: str | None,
    operation: str | None,
    machine_surface_versions: Mapping[str, str] | None,
    origin: str | None,
) -> str:
    capability = capability_for_surface(surface)
    if capability is None or operation is None:
        return "none"
    if not native_wake_supported(surface, origin):
        # The surface still carries its messaging capability — hook delivery
        # is untouched — but nothing here may resume it. Only the operator
        # whose window it is can end the wait.
        return "none"
    if surface_operation_supported(surface, version, operation):
        return str(getattr(capability, operation))
    if (
        operation
        and machine_wake_surface(surface, machine_surface_versions, operation, origin)
        is not None
    ):
        return "supported"
    return "none"


def messageability(
    row: dict[str, Any],
    *,
    liveness: str,
    machine_surface_versions: Mapping[str, str] | None = None,
    force_stopped_route: bool = False,
) -> dict[str, Any]:
    """Project hook delivery and wake facts for one session.

    Hook delivery follows the session's own registered surface and version.
    A stopped session may still be wakeable through a peer binary installed on
    its machine, so the caller passes the relay-reported installed versions and
    the wake route is derived from those rather than from the registered
    surface alone.

    A terminated session is refused outright, read from ``terminated_at`` on
    the row rather than from ``liveness`` — a kill presents as an ordinary
    ``ended`` session, and only the column proves the delivery ban.

    ``wake_authority`` rides beside ``wake_interface`` and ``wake_operation``
    so a reader can tell "no route exists" from "the route belongs to the
    person whose window this is": an ``operator`` surface is never resumed by
    Yoke, and its pending message is delivered by hook injection the moment
    its operator types.

    ``force_stopped_route`` is for a caller that has already decided the
    wake is a stopped-session resume, past what posture and liveness would
    say on their own — an operator asking for one outright, or a starved
    envelope whose own record shows its hook route stopped running. Without
    it the availability answer describes a route the caller is not going to
    take.
    """
    if row.get("terminated_at"):
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
    operation = (
        "message_stopped"
        if force_stopped_route
        else wake_operation(
            "waiting" if row.get("turn_posture") == "waiting" else "idle_timeout",
            liveness,
            surface,
        )
    )
    wake_interface = _wake_interface(
        surface, version, operation, machine_surface_versions, row.get("launch_origin")
    )
    if not surface_version_supported(surface, version):
        return {
            "messageable": False,
            "hook_injection": False,
            "wake_interface": wake_interface,
            "wake_operation": operation,
            "wake_authority": surface_wake_authority(surface)
            if row.get("launch_origin") == "yoke"
            else "operator",
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
        "wake_authority": surface_wake_authority(surface)
        if row.get("launch_origin") == "yoke"
        else "operator",
        "minimum_version": capability.minimum_version,
        "reason": "hook_delivery" if hook_injection else "unsupported_surface",
    }


__all__ = [
    "latest_hook_activity",
    "latest_observed_activity",
    "messageability",
]
