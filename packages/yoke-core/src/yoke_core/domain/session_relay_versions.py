"""Fail-closed version gates for relay-executed surface operations."""

from __future__ import annotations

from packaging.version import InvalidVersion, Version

from yoke_contracts.session_control.capabilities import capability_for_surface


def surface_operation_supported(
    surface: str | None,
    version: str | None,
    operation: str,
) -> bool:
    capability = capability_for_surface(surface)
    if capability is None or operation not in {"create", "message_stopped"}:
        return False
    interface = getattr(capability, operation)
    if interface == "none" or not version:
        return False
    try:
        observed = Version(version)
        floor = Version(capability.minimum_version)
    except InvalidVersion:
        return False
    if interface == "private":
        return observed == floor
    return observed >= floor


__all__ = ["surface_operation_supported"]
