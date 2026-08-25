"""Relay-reported installed surface versions for the sessions on one machine."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from yoke_core.domain import db_backend, json_helper


RelayRoutes = Mapping[str, tuple[dict[str, Any], ...]]


def relay_now_text(now: datetime | None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _document(raw: Any, default: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json_helper.loads_text(str(raw))
    except (TypeError, ValueError):
        return default


def connected_relay_routes(
    conn: Any,
    *,
    now: datetime | None = None,
) -> dict[str, tuple[dict[str, Any], ...]]:
    """Load every still-connected relay's reported surfaces, keyed by machine.

    Callers that derive routing for many sessions read this once and index it,
    so a fleet-wide projection costs one query rather than one per session.
    """
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT machine_id,surface_versions,project_checkouts FROM session_relays "
        f"WHERE state IN ('active','idle') AND connected_until>{marker}",
        (relay_now_text(now),),
    ).fetchall()
    relays: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        relays.setdefault(str(row["machine_id"]), []).append(
            {
                "surface_versions": _document(row["surface_versions"], {}),
                "project_checkouts": _document(row["project_checkouts"], []),
            }
        )
    return {machine: tuple(routes) for machine, routes in relays.items()}


def surface_versions_for(
    routes: tuple[dict[str, Any], ...] | None,
    *,
    project_id: Any,
) -> dict[str, str]:
    """Merge installed versions reported by relays serving this session's project."""
    versions: dict[str, str] = {}
    if project_id is None or not routes:
        return versions
    for route in routes:
        projects = route.get("project_checkouts")
        if not isinstance(projects, list) or str(project_id) not in {
            str(value) for value in projects
        }:
            continue
        reported = route.get("surface_versions")
        if isinstance(reported, dict):
            versions.update({str(key): str(value) for key, value in reported.items()})
    return versions


def machine_surface_versions(
    routes: RelayRoutes,
    *,
    machine_id: Any,
    project_id: Any,
) -> dict[str, str]:
    """Return the versions one session's machine reports for its own project."""
    return surface_versions_for(
        routes.get(str(machine_id or "")),
        project_id=project_id,
    )


__all__ = [
    "connected_relay_routes",
    "machine_surface_versions",
    "relay_now_text",
    "surface_versions_for",
]
