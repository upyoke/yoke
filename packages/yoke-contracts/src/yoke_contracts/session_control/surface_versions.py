"""Fail-closed version gates for native session-control operations."""

from __future__ import annotations

import re

from yoke_contracts.session_control.capabilities import capability_for_surface


_OPERATIONS = frozenset({"create", "message_active", "message_idle", "message_stopped"})
_CURSOR_BUILD_VERSION = re.compile(
    r"^(?P<release>\d{4}\.\d{1,2}\.\d{1,2})-[0-9a-fA-F]{7,40}$"
)
_VERSION = re.compile(
    r"^(?P<release>\d+(?:\.\d+){1,3})"
    r"(?:(?:[-._]?)(?P<label>a|alpha|b|beta|rc|pre|preview)"
    r"(?:[-._]?(?P<number>\d+))?)?$",
    re.IGNORECASE,
)
_PRERELEASE_RANK = {
    "a": 0,
    "alpha": 0,
    "b": 1,
    "beta": 1,
    "pre": 2,
    "preview": 2,
    "rc": 2,
}


def _version_key(surface: str | None, raw: str) -> tuple[int, ...] | None:
    value = raw.strip()
    if str(surface or "").startswith("cursor-"):
        matched = _CURSOR_BUILD_VERSION.fullmatch(value)
        if matched:
            value = matched.group("release")
    matched = _VERSION.fullmatch(value)
    if matched is None:
        return None
    release = tuple(int(part) for part in matched.group("release").split("."))
    padded = release + (0,) * (4 - len(release))
    label = str(matched.group("label") or "").lower()
    if not label:
        return (*padded, 1, 0, 0)
    number = int(matched.group("number") or 0)
    return (*padded, 0, _PRERELEASE_RANK[label], number)


def surface_operation_supported(
    surface: str | None,
    version: str | None,
    operation: str,
) -> bool:
    """Return whether one observed surface is proven for an operation."""
    capability = capability_for_surface(surface)
    if capability is None or operation not in _OPERATIONS:
        return False
    interface = getattr(capability, operation)
    if interface == "none" or not version:
        return False
    observed = _version_key(surface, version)
    floor = _version_key(surface, capability.minimum_version)
    if observed is None or floor is None:
        return False
    if interface == "private":
        return observed == floor
    return observed >= floor


__all__ = ["surface_operation_supported"]
