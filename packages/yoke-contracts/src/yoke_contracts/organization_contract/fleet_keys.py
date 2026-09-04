"""Closed registry for organization-wide fleet policy.

The stored ``organizations.settings`` document contains only explicit
overrides.  Missing leaves resolve to the defaults below, so changing a value
does not require touching every machine and an unknown key can never silently
become policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class FleetKeySpec:
    default: Any
    value_type: type
    meaning: str
    minimum: int | None = None


FLEET_KEY_SPECS: dict[str, FleetKeySpec] = {
    "membership.auto_join_domain_verified": FleetKeySpec(
        False,
        bool,
        "Admit verified email under the organization's identity domain.",
    ),
    "fleet.wake_after_idle_seconds": FleetKeySpec(
        60,
        int,
        "Seconds without hook, tool, or heartbeat activity before wake is eligible.",
        1,
    ),
    "fleet.wake_ack_grace_seconds": FleetKeySpec(
        300,
        int,
        "Seconds before a wake or injection missing acknowledgement is stalled.",
        1,
    ),
    "fleet.stale_alive_probe_seconds": FleetKeySpec(
        900,
        int,
        "Seconds a claim-holding session may stay stale, with its process not "
        "proven dead, before it is sent a status probe.",
        1,
    ),
    "fleet.message_expiry_hours": FleetKeySpec(
        24,
        int,
        "Hours before an undelivered message recipient expires.",
        1,
    ),
    "fleet.max_wake_attempts": FleetKeySpec(
        3,
        int,
        "Maximum native wake attempts for one recipient.",
        1,
    ),
    "fleet.max_body_bytes": FleetKeySpec(
        16384,
        int,
        "Maximum UTF-8 bytes in a message or launch instruction.",
        1,
    ),
    "fleet.broadcast_requires_confirmation": FleetKeySpec(
        True,
        bool,
        "Require exact-recipient confirmation for universe broadcast.",
    ),
    "fleet.auto_select_machine": FleetKeySpec(
        False,
        bool,
        "Allow deterministic relay selection when several are eligible.",
    ),
    "fleet.surface_fallback": FleetKeySpec(
        False,
        bool,
        "Allow an explicitly requested fallback executor surface.",
    ),
    "fleet.launch_deadline_minutes": FleetKeySpec(
        10,
        int,
        "Minutes allowed for a launched conversation to register.",
        1,
    ),
    "fleet.relay_poll_seconds": FleetKeySpec(
        60,
        int,
        "Active relay polling interval in seconds.",
        5,
    ),
    "fleet.relay_idle_after_minutes": FleetKeySpec(
        60,
        int,
        "Minutes without live sessions or jobs before idle cadence.",
        1,
    ),
    "fleet.relay_idle_poll_minutes": FleetKeySpec(
        5,
        int,
        "Relay polling cadence while the machine is idle.",
        1,
    ),
}


class FleetSettingsError(ValueError):
    """An organization fleet-settings document violates the registry."""


def _leaf(document: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = document
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _validate_value(path: str, value: Any) -> None:
    spec = FLEET_KEY_SPECS.get(path)
    if spec is None:
        raise FleetSettingsError(f"unknown organization setting {path!r}")
    if spec.value_type is int:
        valid_type = isinstance(value, int) and not isinstance(value, bool)
    else:
        valid_type = isinstance(value, spec.value_type)
    if not valid_type:
        raise FleetSettingsError(
            f"organization setting {path!r} must be {spec.value_type.__name__}"
        )
    if spec.minimum is not None and int(value) < spec.minimum:
        raise FleetSettingsError(
            f"organization setting {path!r} must be at least {spec.minimum}"
        )


def _flatten(document: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, value in document.items():
        if not isinstance(key, str) or not key:
            raise FleetSettingsError(
                "organization setting keys must be non-empty strings"
            )
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, Mapping):
            flattened.update(_flatten(value, path))
        else:
            flattened[path] = value
    return flattened


def _assign(document: dict[str, Any], path: str, value: Any) -> None:
    current = document
    parts = path.split(".")
    for part in parts[:-1]:
        child = current.get(part)
        if child is None:
            child = {}
            current[part] = child
        if not isinstance(child, dict):
            raise FleetSettingsError(
                f"organization setting container {part!r} is not an object"
            )
        current = child
    current[parts[-1]] = value


def validate_fleet_settings(document: Mapping[str, Any]) -> None:
    if not isinstance(document, Mapping):
        raise FleetSettingsError("organization settings must be an object")
    for path, value in _flatten(document).items():
        _validate_value(path, value)


def default_fleet_settings() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for path, spec in FLEET_KEY_SPECS.items():
        _assign(result, path, spec.default)
    return result


def get_fleet_setting(document: Mapping[str, Any], path: str) -> tuple[Any, bool]:
    spec = FLEET_KEY_SPECS.get(path)
    if spec is None:
        raise FleetSettingsError(f"unknown organization setting {path!r}")
    found, value = _leaf(document, path)
    if not found:
        return spec.default, True
    _validate_value(path, value)
    return value, False


def merge_fleet_settings(
    document: Mapping[str, Any],
    changes: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    validate_fleet_settings(document)
    merged = _deep_copy(document)
    flattened = _flatten(changes)
    for path, value in flattened.items():
        _validate_value(path, value)
        _assign(merged, path, value)
    return merged, sorted(flattened)


def _deep_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    copied: dict[str, Any] = {}
    for key, child in value.items():
        copied[key] = _deep_copy(child) if isinstance(child, Mapping) else child
    return copied


__all__ = [
    "FLEET_KEY_SPECS",
    "FleetKeySpec",
    "FleetSettingsError",
    "default_fleet_settings",
    "get_fleet_setting",
    "merge_fleet_settings",
    "validate_fleet_settings",
]
