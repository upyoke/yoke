"""Fail-closed version gates for native session-control operations."""

from __future__ import annotations

import re
from typing import Mapping

from yoke_contracts.session_control.capabilities import (
    capabilities_for_harness,
    capability_for_surface,
    native_wake_supported,
)
from yoke_contracts.session_control.private_route_versions import (
    private_route_version_qualified,
)


_WAKE_OPERATIONS = frozenset({"message_active", "message_idle", "message_stopped"})
_OPERATIONS = frozenset({"create", *_WAKE_OPERATIONS})
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
    if operation in _WAKE_OPERATIONS and not native_wake_supported(surface):
        # An operator-driven surface has no wake route at any version: the
        # only thing that resumes it is the person whose window it is.
        return False
    interface = getattr(capability, operation)
    if interface == "none" or not version:
        return False
    surface_floor_qualified = surface_version_supported(surface, version)
    if not surface_floor_qualified:
        return False
    if interface == "private":
        return private_route_version_qualified(
            surface,
            version,
            operation,
            surface_floor_qualified=surface_floor_qualified,
        )
    return True


def surface_version_supported(surface: str | None, version: str | None) -> bool:
    """Return whether an observed surface meets its capability version floor."""
    capability = capability_for_surface(surface)
    if capability is None or not version:
        return False
    return surface_version_meets_floor(surface, version, capability.minimum_version)


def surface_version_meets_floor(
    surface: str | None,
    observed_version: str | None,
    minimum_version: str | None,
) -> bool:
    """Return whether one observed surface version meets an explicit floor."""
    if not observed_version or not minimum_version:
        return False
    observed = _version_key(surface, observed_version)
    floor = _version_key(surface, minimum_version)
    return bool(observed is not None and floor is not None and observed >= floor)


def machine_wake_executor_surface(
    surface: str | None,
    operation: str,
) -> str | None:
    """Name the same-machine binary that executes a peer wake."""
    target = str(surface or "")
    if not native_wake_supported(target):
        # The peer binary could technically resume this conversation, which
        # is exactly the failure: the wake would land in a fork of the
        # transcript its operator is reading. Naming no executor is what
        # keeps every caller from carrying that wake onward.
        return None
    if operation == "message_stopped" and target in _CLAUDE_FAMILY_SURFACES:
        return _CLAUDE_RESUME_SURFACE
    return None


def machine_wake_surface(
    surface: str | None,
    machine_surface_versions: Mapping[str, str] | None,
    operation: str,
) -> tuple[str, str] | None:
    """Return the qualified same-machine peer binary for one wake operation."""
    executor_surface = machine_wake_executor_surface(surface, operation)
    if executor_surface is None:
        return None
    version = (machine_surface_versions or {}).get(executor_surface)
    if not surface_operation_supported(executor_surface, version, operation):
        return None
    return executor_surface, str(version)


def machine_stopped_wake_surface(
    surface: str | None,
    machine_surface_versions: Mapping[str, str] | None,
) -> tuple[str, str] | None:
    """Return the binary that wakes a stopped session, with its version.

    Every Claude app on one machine shares a single transcript store, so the
    installed CLI resumes a stopped session whichever app registered it. The
    gate is therefore the version of the binary that executes the resume, not
    the version recorded for the surface the session was born in — and every
    caller carrying that wake onward names the same executing binary, because
    the surface the session registered under has no resume route of its own.

    A surface whose wake authority is the operator has no peer route at all:
    sharing a transcript store is what would let the CLI resume the window a
    person is reading, which is the fork this refuses rather than enables.
    """
    return machine_wake_surface(surface, machine_surface_versions, "message_stopped")


def machine_stopped_wake_supported(
    surface: str | None,
    machine_surface_versions: Mapping[str, str] | None,
) -> bool:
    """Return whether a machine's installed CLI can wake a stopped Claude session."""
    return machine_stopped_wake_surface(surface, machine_surface_versions) is not None


__all__ = [
    "machine_wake_executor_surface",
    "machine_wake_surface",
    "machine_stopped_wake_supported",
    "machine_stopped_wake_surface",
    "surface_operation_supported",
    "surface_version_meets_floor",
    "surface_version_supported",
]
