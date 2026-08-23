"""Canonical-first authorization for one relay wake candidate."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.session_control.private_route_qualification import (
    PrivateRouteQualificationGrant,
)
from yoke_core.domain.session_relay_types import RelayHeartbeat
from yoke_core.domain.session_relay_versions import (
    wake_candidate_supported,
    wake_operation,
)


def authorize_wake_candidate(
    conn: Any,
    candidate: Mapping[str, Any],
    heartbeat: RelayHeartbeat,
    *,
    route: str,
) -> tuple[bool, PrivateRouteQualificationGrant | None]:
    """Return canonical authority first, consulting a grant only on failure."""
    return authorize_wake_versions(
        conn,
        candidate,
        heartbeat.surface_versions,
        route=route,
    )


def authorize_wake_versions(
    conn: Any,
    candidate: Mapping[str, Any],
    surface_versions: Mapping[str, str],
    *,
    route: str,
) -> tuple[bool, PrivateRouteQualificationGrant | None]:
    """Authorize one exact route without broadening another route's grant."""
    if wake_candidate_supported(candidate, surface_versions):
        return True, None
    surface = str(candidate.get("executor_surface") or "")
    version = str(candidate.get("executor_version") or "")
    if surface_versions.get(surface) != version:
        return False, None
    operation = wake_operation(
        str(candidate.get("wake_mode") or ""),
        str(candidate.get("liveness") or ""),
    )
    if operation is None:
        return False, None
    from yoke_core.domain.session_private_route_qualification import (
        PrivateRouteQualificationError,
        qualification_for_message,
    )

    try:
        grant = qualification_for_message(
            conn,
            candidate,
            operation=operation,
            route=route,
        )
    except PrivateRouteQualificationError:
        return False, None
    return grant is not None, grant


__all__ = ["authorize_wake_candidate", "authorize_wake_versions"]
