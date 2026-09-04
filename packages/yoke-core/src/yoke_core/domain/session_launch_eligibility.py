"""Relay eligibility derived from live launch evidence."""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.session_control.capabilities import capability_for_surface
from yoke_contracts.session_control.surface_versions import (
    surface_operation_supported,
)
from yoke_core.domain import db_backend
from yoke_core.domain.session_launch_capacity import (
    MACHINE_AT_CAPACITY,
    MachineCapacity,
    machine_capacity,
)
from yoke_core.domain.session_launch_types import (
    EligibilitySnapshot,
    EligibleRelay,
)
from yoke_core.domain.session_surface_policy import (
    SURFACE_DISABLED_REJECTION,
    live_mark,
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
        f"SELECT slug FROM projects WHERE id = {marker}",
        (project_id,),
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
    return surface_operation_supported(surface, offered, "create")


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
    from connected relay rows, their advertised surface versions, their
    registered project checkout identifiers, and the lanes already running
    or in flight on each machine against the cap its relay published.
    """
    capability = capability_for_surface(surface)
    if capability is None or capability.create == "none":
        return EligibilitySnapshot((), rejection_codes=("unsupported_surface",))

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    params: list[Any] = []
    machine_clause = ""
    if machine_id:
        machine_clause = f" WHERE machine_id = {marker}"
        params.append(machine_id)
    rows = conn.execute(
        "SELECT relay_id, machine_id, surface_versions, project_checkouts, "
        "last_seen_at, state, connected_until, machine_capacity, hostname, "
        "actor_id "
        "FROM session_relays"
        f"{machine_clause} ORDER BY last_seen_at DESC, relay_id ASC",
        tuple(params),
    ).fetchall()
    project_keys = _project_keys(conn, project_id)
    considered: set[str] = set()
    selected_by_machine: dict[str, EligibleRelay] = {}
    capacities: dict[str, MachineCapacity] = {}
    rejected: set[str] = set()
    for row in rows:
        relay_machine = str(_value(row, "machine_id", 1))
        considered.add(relay_machine)
        row_rejected = False
        state = str(_value(row, "state", 5))
        connected_until = str(_value(row, "connected_until", 6))
        if state not in {"active", "idle"} or connected_until < now:
            rejected.add("liveness_expired")
            row_rejected = True
        if not _serves_project(_value(row, "project_checkouts", 3), project_keys):
            rejected.add("project_checkout_missing")
            row_rejected = True
        versions = _json(_value(row, "surface_versions", 2), {})
        offered = versions.get(surface) if isinstance(versions, dict) else None
        if not isinstance(offered, str) or not offered.strip():
            rejected.add("surface_absent")
            row_rejected = True
        elif not _allowed_version(surface, offered):
            rejected.add("version_below_floor")
            row_rejected = True
        if live_mark(conn, relay_machine, surface) is not None:
            rejected.add(SURFACE_DISABLED_REJECTION)
            row_rejected = True
        if row_rejected:
            continue
        if relay_machine in selected_by_machine:
            continue
        if relay_machine not in capacities:
            capacities[relay_machine] = machine_capacity(
                conn,
                machine_id=relay_machine,
                capacity_document=_value(row, "machine_capacity", 7),
                now=now,
            )
        if capacities[relay_machine].at_capacity:
            rejected.add(MACHINE_AT_CAPACITY)
            continue
        try:
            owner_actor_id = int(_value(row, "actor_id", 9))
        except (TypeError, ValueError):
            owner_actor_id = None
        selected_by_machine[relay_machine] = EligibleRelay(
            relay_id=str(_value(row, "relay_id", 0)),
            machine_id=relay_machine,
            surface=surface,
            version=offered,
            last_seen_at=str(_value(row, "last_seen_at", 4)),
            hostname=str(_value(row, "hostname", 8) or ""),
            owner_actor_id=owner_actor_id,
        )
    if not rows:
        rejected.add("relay_absent")
    return EligibilitySnapshot(
        tuple(selected_by_machine.values()),
        considered_machine_ids=tuple(sorted(considered)),
        rejection_codes=tuple(sorted(rejected)),
        machine_capacity=tuple(capacities[machine] for machine in sorted(capacities)),
    )


__all__ = ["derive_launch_eligibility"]
