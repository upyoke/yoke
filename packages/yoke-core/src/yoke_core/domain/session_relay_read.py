"""Actor-visible public projections of machine-relay health."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain.actor_display import actor_display_name
from yoke_core.domain.actor_project_visibility import actor_visible_project_ids
from yoke_core.domain.actors import ActorError
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.session_launch_capacity import machine_capacity
from yoke_core.domain.session_relay_storage import marker
from yoke_core.domain.session_relay_types import SessionRelayError
from yoke_contracts.session_control.relay_health import sanitize_relay_health
from yoke_contracts.session_control.plan_limits import sanitize_plan_limits


def _value(row: Any, key: str, index: int) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return row[index]


def _document(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value or ""))
    except (TypeError, ValueError):
        return fallback


def _owner_names(conn: Any, actor_ids: set[int]) -> dict[int, str]:
    """Resolve each owning actor once, so a roster is not one query per card."""
    names: dict[int, str] = {}
    for actor_id in sorted(actor_ids):
        try:
            names[actor_id] = actor_display_name(conn, actor_id)
        except ActorError:
            names[actor_id] = ""
    return names


def list_visible_relays(
    conn: Any,
    *,
    actor_id: int,
    project: str | None = None,
    state: str | None = None,
    limit: int = 100,
    now: str | None = None,
) -> list[dict[str, Any]]:
    """Return safe relay facts intersected with actor-visible projects."""
    from yoke_core.domain.session_relay_storage import utc_now

    current = now or utc_now()
    visible = actor_visible_project_ids(conn, actor_id)
    requested_project = resolve_project_id(conn, project) if project else None
    if requested_project is not None and requested_project not in visible:
        raise SessionRelayError(
            "permission_denied", "relay project is not visible to this actor"
        )

    params: list[Any] = []
    where = ""
    if state:
        where = f" WHERE state={marker(conn)}"
        params.append(state)
    rows = conn.execute(
        "SELECT relay_id,machine_id,hostname,relay_version,surface_versions,"
        "project_checkouts,first_seen_at,last_seen_at,connected_until,state,"
        "last_job_at,actor_id,relay_health,surface_plan_limits,machine_capacity "
        "FROM session_relays"
        + where
        + " ORDER BY last_seen_at DESC,relay_id",
        tuple(params),
    ).fetchall()

    # A machine roster holds many more relays than distinct owners, so
    # resolve each owner's name once rather than once per card.
    owners = _owner_names(
        conn,
        {int(_value(row, "actor_id", 11)) for row in rows},
    )
    from yoke_core.domain.session_surface_policy import list_marks

    marks_by_machine: dict[str, list[dict[str, Any]]] = {}
    for mark in list_marks(conn):
        marks_by_machine.setdefault(str(mark["machine_id"]), []).append(mark)

    result: list[dict[str, Any]] = []
    for row in rows:
        projects = {
            int(value)
            for value in _document(_value(row, "project_checkouts", 5), [])
            if str(value).isdigit()
        }
        visible_projects = sorted(projects & visible)
        if requested_project is not None and requested_project not in projects:
            continue
        if not visible_projects:
            continue
        connected_until = _value(row, "connected_until", 8)
        machine_id = str(_value(row, "machine_id", 1))
        capacity = machine_capacity(
            conn,
            machine_id=machine_id,
            capacity_document=_value(row, "machine_capacity", 14),
            now=current,
        )
        result.append(
            {
                "relay_id": str(_value(row, "relay_id", 0)),
                # The owner's name, never the raw actor id: a relay is visible
                # to everyone who shares one of its projects, and they need to
                # know whose machine they are about to launch onto.
                "owner": owners.get(int(_value(row, "actor_id", 11)), ""),
                "machine_id": machine_id,
                "hostname": str(_value(row, "hostname", 2)),
                "relay_version": _value(row, "relay_version", 3),
                "surface_versions": _document(_value(row, "surface_versions", 4), {}),
                "project_ids": visible_projects,
                "first_seen_at": _value(row, "first_seen_at", 6),
                "last_seen_at": _value(row, "last_seen_at", 7),
                "connected_until": connected_until,
                "liveness": "connected"
                if str(connected_until or "") >= current
                else "silent",
                "state": str(_value(row, "state", 9)),
                "last_job_at": _value(row, "last_job_at", 10),
                "relay_health": sanitize_relay_health(
                    _document(_value(row, "relay_health", 12), {})
                ),
                "plan_limits": sanitize_plan_limits(
                    _document(_value(row, "surface_plan_limits", 13), {})
                ),
                "capacity": capacity.to_dict(),
                "surface_policies": marks_by_machine.get(
                    str(_value(row, "machine_id", 1)), []
                ),
            }
        )
        if len(result) >= limit:
            break
    return result


__all__ = ["list_visible_relays"]
