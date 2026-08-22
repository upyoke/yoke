"""Relay eligibility derived from live launch evidence."""

from __future__ import annotations

import json
from typing import Any

from packaging.version import InvalidVersion, Version

from yoke_contracts.session_control.capabilities import capability_for_surface
from yoke_core.domain import db_backend
from yoke_core.domain.session_launch_types import (
    EligibilitySnapshot,
    EligibleRelay,
)


def _value(row: Any, name: str, index: int) -> Any:
    try:
        return row[name]
    except (KeyError, TypeError, IndexError):
        return row[index]


def _json(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(str(value))
    except (json.JSONDecodeError, TypeError, ValueError):
        return default
    return parsed


def _project_keys(conn: Any, project_id: int) -> set[str]:
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT slug FROM projects WHERE id = {marker}", (project_id,),
    ).fetchone()
    keys = {str(project_id)}
    if row is not None:
        keys.add(str(_value(row, "slug", 0)))
    return keys


def _serves_project(raw: Any, keys: set[str]) -> bool:
    projects = _json(raw, [])
    if isinstance(projects, dict):
        offered = {str(key) for key in projects}
    elif isinstance(projects, list):
        offered = {str(value) for value in projects}
    else:
        return False
    return bool(keys & offered)


def _allowed_version(surface: str, offered: str) -> bool:
    capability = capability_for_surface(surface)
    if capability is None or capability.create == "none":
        return False
    try:
        return Version(offered) >= Version(capability.minimum_version)
    except InvalidVersion:
        return False


def derive_launch_eligibility(
    conn: Any,
    *,
    project_id: int,
    surface: str,
    machine_id: str | None,
    now: str,
) -> EligibilitySnapshot:
    """Return one freshest eligible relay per machine.

    Eligibility is never accepted from the create request. It is recomputed
    from connected relay rows, their advertised surface versions, and their
    registered project checkout identifiers.
    """
    capability = capability_for_surface(surface)
    if capability is None or capability.create == "none":
        return EligibilitySnapshot((), rejection_codes=("unsupported_surface",))

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    params: list[Any] = [now]
    machine_clause = ""
    if machine_id:
        machine_clause = f" AND machine_id = {marker}"
        params.append(machine_id)
    rows = conn.execute(
        "SELECT relay_id, machine_id, surface_versions, project_checkouts, "
        "last_seen_at FROM session_relays "
        f"WHERE state IN ('active','idle') AND connected_until >= {marker}"
        f"{machine_clause} ORDER BY last_seen_at DESC, relay_id ASC",
        tuple(params),
    ).fetchall()
    project_keys = _project_keys(conn, project_id)
    considered: set[str] = set()
    selected_by_machine: dict[str, EligibleRelay] = {}
    rejected: set[str] = set()
    for row in rows:
        relay_machine = str(_value(row, "machine_id", 1))
        considered.add(relay_machine)
        if not _serves_project(_value(row, "project_checkouts", 3), project_keys):
            rejected.add("project_checkout_missing")
            continue
        versions = _json(_value(row, "surface_versions", 2), {})
        offered = versions.get(surface) if isinstance(versions, dict) else None
        if not isinstance(offered, str) or not _allowed_version(surface, offered):
            rejected.add("version_mismatch")
            continue
        if relay_machine in selected_by_machine:
            continue
        selected_by_machine[relay_machine] = EligibleRelay(
            relay_id=str(_value(row, "relay_id", 0)),
            machine_id=relay_machine,
            surface=surface,
            version=offered,
            last_seen_at=str(_value(row, "last_seen_at", 4)),
        )
    return EligibilitySnapshot(
        tuple(selected_by_machine.values()),
        tuple(sorted(considered)),
        tuple(sorted(rejected)),
    )


__all__ = ["derive_launch_eligibility"]
