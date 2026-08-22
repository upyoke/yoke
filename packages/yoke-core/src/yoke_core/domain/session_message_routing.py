"""Session liveness and capability-derived message routing facts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from packaging.version import InvalidVersion, Version

from yoke_contracts.session_control.capabilities import capability_for_surface
from yoke_core.domain.session_staleness import activity_is_stale
from yoke_core.domain.session_message_types import parse_timestamp


def latest_hook_activity(row: dict[str, Any]) -> datetime | None:
    candidates = [
        parse_timestamp(row.get("last_tool_call_at")),
        parse_timestamp(row.get("last_injected_at")),
    ]
    present = [value for value in candidates if value is not None]
    return max(present) if present else None


def session_liveness(row: dict[str, Any], *, now: datetime) -> str:
    if row.get("ended_at"):
        return "ended"
    raw_activity = max(
        str(row.get("last_heartbeat") or ""),
        str(row.get("last_tool_call_at") or ""),
    )
    if activity_is_stale(raw_activity, executor=row.get("executor"), now=now):
        return "stale"
    return "active"


def _version_at_floor(observed: str | None, minimum: str) -> bool:
    if not observed:
        return False
    try:
        return Version(observed) >= Version(minimum)
    except InvalidVersion:
        return False


def messageability(row: dict[str, Any], *, liveness: str) -> dict[str, Any]:
    surface = str(row.get("executor_surface") or "")
    capability = capability_for_surface(surface)
    if capability is None:
        return {
            "messageable": False,
            "hook_injection": False,
            "wake_interface": "none",
            "reason": "unknown_surface",
        }
    version_ok = _version_at_floor(
        str(row.get("executor_version") or "") or None,
        capability.minimum_version,
    )
    if not version_ok:
        return {
            "messageable": False,
            "hook_injection": False,
            "wake_interface": "none",
            "reason": "version_below_floor_or_unknown",
            "minimum_version": capability.minimum_version,
        }
    wake_interface = {
        "active": capability.message_active,
        "stale": capability.message_idle,
        "ended": capability.message_stopped,
    }.get(liveness, "none")
    hook_injection = bool(capability.inject_events)
    return {
        "messageable": hook_injection,
        "hook_injection": hook_injection,
        "inject_events": list(capability.inject_events),
        "wake_interface": wake_interface,
        "minimum_version": capability.minimum_version,
        "reason": "hook_delivery" if hook_injection else "unsupported_surface",
    }


__all__ = ["latest_hook_activity", "messageability", "session_liveness"]
