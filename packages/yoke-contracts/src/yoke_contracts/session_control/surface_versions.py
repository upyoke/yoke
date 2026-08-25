"""Fail-closed version gates for native session-control operations."""

from __future__ import annotations

import re
from typing import Mapping

from yoke_contracts.session_control.capabilities import (
    capabilities_for_harness,
    capability_for_surface,
)
from yoke_contracts.session_control.private_route_versions import (
    private_route_version_qualified,
)


_OPERATIONS = frozenset({"create", "message_active", "message_idle", "message_stopped"})
_CURSOR_BUILD_VERSION = re.compile(
    r"^(?P<release>\d{4}\.\d{1,2}\.\d{1,2})-[0-9a-fA-F]{7,40}$"
)
_CODEX_CLI_BUILD_VERSION = re.compile(
    r"^(?P<release>\d+(?:\.\d+){1,3}"
    r"-(?:a|alpha|b|beta|rc|pre|preview)[-._]?\d+)\.\d+$",
    re.IGNORECASE,
)
_VERSION = re.compile(
    r"^(?P<release>\d+(?:\.\d+){1,3})"
    r"(?:(?:[-._]?)(?P<label>a|alpha|b|beta|rc|pre|preview)"
    r"(?:[-._]?(?P<number>\d+))?)?$",
    re.IGNORECASE,
)
_CLAUDE_RESUME_SURFACE = "claude-cli"
_CLAUDE_FAMILY_SURFACES = frozenset(capabilities_for_harness("claude-code"))
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
    elif surface == "codex-cli":
        matched = _CODEX_CLI_BUILD_VERSION.fullmatch(value)
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
    if not surface_version_supported(surface, version):
        return False
    if interface == "private":
        return private_route_version_qualified(surface, version, operation)
    return True


def surface_version_supported(surface: str | None, version: str | None) -> bool:
    """Return whether an observed surface meets its capability version floor."""
    capability = capability_for_surface(surface)
    if capability is None or not version:
        return False
    observed = _version_key(surface, version)
    floor = _version_key(surface, capability.minimum_version)
    return bool(observed is not None and floor is not None and observed >= floor)


def machine_stopped_wake_surface(
    surface: str | None,
    machine_surface_versions: Mapping[str, str] | None,
) -> tuple[str, str] | None:
    """Return the binary that wakes a stopped Claude session, with its version.

    Every Claude app on one machine shares a single transcript store, so the
    installed CLI resumes a stopped session whichever app registered it. The
    gate is therefore the version of the binary that executes the resume, not
    the version recorded for the surface the session was born in — and every
    caller carrying that wake onward names the same executing binary, because
    the surface the session registered under has no resume route of its own.
    """
    if str(surface or "") not in _CLAUDE_FAMILY_SURFACES:
        return None
    version = (machine_surface_versions or {}).get(_CLAUDE_RESUME_SURFACE)
    if not surface_operation_supported(
        _CLAUDE_RESUME_SURFACE, version, "message_stopped"
    ):
        return None
    return _CLAUDE_RESUME_SURFACE, str(version)


def machine_stopped_wake_supported(
    surface: str | None,
    machine_surface_versions: Mapping[str, str] | None,
) -> bool:
    """Return whether a machine's installed CLI can wake a stopped Claude session."""
    return machine_stopped_wake_surface(surface, machine_surface_versions) is not None


__all__ = [
    "machine_stopped_wake_supported",
    "machine_stopped_wake_surface",
    "surface_operation_supported",
    "surface_version_supported",
]
