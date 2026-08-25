"""Canonical-first authorization for one relay wake candidate."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.session_control.private_route_qualification import (
    PrivateRouteQualificationGrant,
)
from yoke_core.domain.session_relay_types import RelayHeartbeat
from yoke_core.domain.session_relay_versions import (
    wake_execution_surface,
    wake_operation,
)


WakeExecution = tuple[str, str]


def authorize_wake_candidate(
    conn: Any,
    candidate: Mapping[str, Any],
    heartbeat: RelayHeartbeat,
    *,
    route: str,
) -> tuple[WakeExecution | None, PrivateRouteQualificationGrant | None]:
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
) -> tuple[WakeExecution | None, PrivateRouteQualificationGrant | None]:
    """Name the binary authorized for one exact route, or refuse it.

    Authorization and execution are one answer: a route is available only
    because some installed binary proves the operation, and that binary is
    what the caller must hand the relay. Refusal is a missing execution
    surface rather than a bare false, so no caller can carry an authorized
    wake onward under a surface that cannot perform it.
    """
    execution = wake_execution_surface(candidate, surface_versions)
    if execution is not None:
        return execution, None
    surface = str(candidate.get("executor_surface") or "")
    version = str(candidate.get("executor_version") or "")
    # A one-shot grant proves the exact installed binary that will consume it;
    # a floor here would replay build-specific stage evidence onto another build.
    if surface_versions.get(surface) != version:
        return None, None
    operation = wake_operation(
        str(candidate.get("wake_mode") or ""),
        str(candidate.get("liveness") or ""),
    )
    if operation is None:
        return None, None
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
        return None, None
    if grant is None:
        return None, None
    return (surface, version), grant


__all__ = ["authorize_wake_candidate", "authorize_wake_versions"]
