"""Exact versions qualified for private native session-control routes."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from yoke_contracts.session_control.capabilities import (
    SESSION_SURFACE_CAPABILITIES,
)


PrivateRouteKey = tuple[str, str]


def _minimum_version(surface: str) -> str:
    return SESSION_SURFACE_CAPABILITIES[surface].minimum_version


PRIVATE_ROUTE_VERSION_QUALIFICATIONS: Mapping[PrivateRouteKey, frozenset[str]] = (
    MappingProxyType(
        {
            ("claude-cli", "message_active"): frozenset(
                {_minimum_version("claude-cli")}
            ),
            ("claude-cli", "message_idle"): frozenset({_minimum_version("claude-cli")}),
            ("claude-desktop", "message_active"): frozenset(
                {_minimum_version("claude-desktop")}
            ),
            ("claude-desktop", "message_idle"): frozenset(
                {_minimum_version("claude-desktop")}
            ),
            ("claude-vscode", "message_idle"): frozenset(
                {_minimum_version("claude-vscode")}
            ),
        }
    )
)


def _private_capability_keys() -> set[PrivateRouteKey]:
    operations = ("create", "message_active", "message_idle", "message_stopped")
    return {
        (surface, operation)
        for surface, capability in SESSION_SURFACE_CAPABILITIES.items()
        for operation in operations
        if getattr(capability, operation) == "private"
    }


if set(PRIVATE_ROUTE_VERSION_QUALIFICATIONS) != _private_capability_keys():
    raise RuntimeError("private route version qualifications must cover every route")


def private_route_version_qualified(
    surface: str | None,
    version: str | None,
    operation: str,
) -> bool:
    """Return whether an exact surface version is qualified for a private route."""
    if not version:
        return False
    qualified = PRIVATE_ROUTE_VERSION_QUALIFICATIONS.get(
        (str(surface or ""), operation), frozenset()
    )
    return version in qualified


__all__ = [
    "PRIVATE_ROUTE_VERSION_QUALIFICATIONS",
    "private_route_version_qualified",
]
