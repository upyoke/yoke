"""Version policies qualified for private native session-control routes."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from yoke_contracts.session_control.capabilities import (
    SESSION_SURFACE_CAPABILITIES,
)


PrivateRouteKey = tuple[str, str]


@dataclass(frozen=True)
class PrivateRouteVersionQualification:
    """An exact allowlist or the surface capability's minimum-version floor."""

    exact_versions: frozenset[str] | None

    @classmethod
    def exact(cls, *versions: str) -> "PrivateRouteVersionQualification":
        return cls(frozenset(versions))

    @classmethod
    def surface_floor(cls) -> "PrivateRouteVersionQualification":
        return cls(None)

    @property
    def uses_surface_floor(self) -> bool:
        return self.exact_versions is None

    def accepts(self, version: str, *, surface_floor_qualified: bool) -> bool:
        if self.exact_versions is None:
            return surface_floor_qualified
        return version in self.exact_versions


def _private_capability_keys() -> set[PrivateRouteKey]:
    operations = ("create", "message_active", "message_idle", "message_stopped")
    return {
        (surface, operation)
        for surface, capability in SESSION_SURFACE_CAPABILITIES.items()
        for operation in operations
        if getattr(capability, operation) == "private"
    }


PRIVATE_ROUTE_VERSION_QUALIFICATIONS: Mapping[
    PrivateRouteKey, PrivateRouteVersionQualification
] = MappingProxyType(
    {
        key: PrivateRouteVersionQualification.surface_floor()
        for key in _private_capability_keys()
    }
)


if set(PRIVATE_ROUTE_VERSION_QUALIFICATIONS) != _private_capability_keys():
    raise RuntimeError("private route version qualifications must cover every route")


def private_route_version_qualified(
    surface: str | None,
    version: str | None,
    operation: str,
    *,
    surface_floor_qualified: bool,
) -> bool:
    """Return whether a surface version satisfies its private-route policy."""
    if not version:
        return False
    qualification = PRIVATE_ROUTE_VERSION_QUALIFICATIONS.get(
        (str(surface or ""), operation)
    )
    return bool(
        qualification is not None
        and qualification.accepts(
            version, surface_floor_qualified=surface_floor_qualified
        )
    )


__all__ = [
    "PRIVATE_ROUTE_VERSION_QUALIFICATIONS",
    "PrivateRouteVersionQualification",
    "private_route_version_qualified",
]
