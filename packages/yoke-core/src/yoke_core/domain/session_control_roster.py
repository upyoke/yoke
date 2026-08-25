"""Read-time enrichment for the operator fleet-session roster."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping

from yoke_contracts.session_control.roster import (
    SESSION_CONTROL_ROSTER_DISPLAY_FIELDS,
)
from yoke_contracts.session_control.surface_versions import (
    machine_stopped_wake_supported,
)
from yoke_core.domain import db_backend
from yoke_core.domain.session_list_fields import SESSION_LIST_FIELDS
from yoke_core.domain.session_message_routing import messageability
from yoke_core.domain.session_relay_machine_versions import (
    connected_relay_routes,
    surface_versions_for,
)
from yoke_core.domain.session_relay_types import WakeMode
from yoke_core.domain.session_relay_versions import wake_candidate_supported


SESSION_CONTROL_ROSTER_FIELDS = tuple(
    dict.fromkeys((*SESSION_LIST_FIELDS, *SESSION_CONTROL_ROSTER_DISPLAY_FIELDS))
)


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row_dict(row: Any) -> dict[str, Any]:
    return {str(key): row[key] for key in row.keys()}


def _identity_facts(
    conn: Any,
    session_ids: Iterable[str],
) -> dict[str, dict[str, Any]]:
    ids = tuple(dict.fromkeys(session_ids))
    if not ids:
        return {}
    marker = _marker(conn)
    rows = conn.execute(
        "SELECT session_id,project_id,executor_surface,executor_version,machine_id,"
        "last_heartbeat,last_tool_call_at,ended_at,turn_posture,turn_posture_at "
        "FROM harness_sessions WHERE session_id IN ("
        + ",".join(marker for _ in ids)
        + ")",
        ids,
    ).fetchall()
    return {str(row["session_id"]): _row_dict(row) for row in rows}


def _wake_route_available(
    merged: dict[str, Any],
    *,
    liveness: str,
    versions: Mapping[str, str],
    wake_operation: str | None,
) -> bool:
    surface = str(merged.get("executor_surface") or "")
    candidate = {
        "executor_surface": surface,
        "executor_version": str(merged.get("executor_version") or ""),
        "wake_mode": (
            WakeMode.WAITING.value
            if merged.get("turn_posture") == "waiting"
            else WakeMode.IDLE_TIMEOUT.value
        ),
        "liveness": liveness,
    }
    if wake_candidate_supported(candidate, versions):
        return True
    return wake_operation == "message_stopped" and machine_stopped_wake_supported(
        surface, versions
    )


def _active_worktrees(
    conn: Any,
    session_ids: Iterable[str],
) -> dict[str, str]:
    ids = tuple(dict.fromkeys(session_ids))
    if not ids:
        return {}
    marker = _marker(conn)
    rows = conn.execute(
        "SELECT wc.session_id,"
        "COALESCE(task_lane.path,item_lane.path,'') AS worktree_path,"
        "COALESCE(task_lane.branch,item_lane.branch,'') AS worktree_branch "
        "FROM work_claims wc "
        "LEFT JOIN epic_tasks et ON wc.target_kind='epic_task' "
        "AND et.epic_id=wc.epic_id AND et.task_num=wc.task_num "
        "LEFT JOIN item_worktrees task_lane ON task_lane.id=et.item_worktree_id "
        "AND task_lane.state='active' "
        "LEFT JOIN item_worktrees item_lane ON item_lane.id=("
        "SELECT iw.id FROM item_worktrees iw WHERE wc.target_kind='item' "
        "AND iw.item_id=wc.item_id AND iw.state='active' "
        "ORDER BY CASE iw.lane_role WHEN 'integration' THEN 0 ELSE 1 END,"
        "iw.id LIMIT 1) "
        "WHERE wc.released_at IS NULL AND wc.session_id IN ("
        + ",".join(marker for _ in ids)
        + ") ORDER BY wc.claimed_at,wc.id",
        ids,
    ).fetchall()
    worktrees: dict[str, str] = {}
    for row in rows:
        session_id = str(row["session_id"])
        lane = str(row["worktree_path"] or row["worktree_branch"] or "")
        if lane and session_id not in worktrees:
            worktrees[session_id] = lane
    return worktrees


def _focus(row: dict[str, Any]) -> str:
    current = str(row.get("current_item") or "")
    if current:
        return current
    claims = row.get("claims") or []
    if claims:
        return str(claims[0].get("target") or "")
    return ""


def _project_row(
    row: dict[str, Any],
    *,
    identity: dict[str, Any],
    connected_relays: dict[str, tuple[dict[str, Any], ...]],
    worktree: str | None,
) -> dict[str, Any]:
    merged = {**row, **identity}
    machine_id = str(merged.get("machine_id") or "")
    routes = connected_relays.get(machine_id, ())
    relay_connected = bool(machine_id and routes)
    liveness = str(row.get("liveness") or "ended")
    versions = surface_versions_for(routes, project_id=merged.get("project_id"))
    routing = messageability(
        merged,
        liveness=liveness,
        machine_surface_versions=versions,
    )
    routing["relay_connected"] = relay_connected
    routing["wake_available"] = bool(
        routing.get("wake_interface") != "none"
        and _wake_route_available(
            merged,
            liveness=liveness,
            versions=versions,
            wake_operation=routing.get("wake_operation"),
        )
    )
    role = row.get("work_role")
    claims = row.get("claims") or []
    if not role and claims:
        role = claims[0].get("target_kind")
    return {
        **row,
        "focus": _focus(row),
        "role": role,
        "worktree": worktree or row.get("workspace"),
        "executor_version": merged.get("executor_version"),
        "machine_id": merged.get("machine_id"),
        "turn_posture": merged.get("turn_posture") or "unknown",
        "relay": "connected"
        if relay_connected
        else ("unavailable" if machine_id else ""),
        "messageability": routing,
    }


def session_control_roster_result(
    rows: list[dict[str, Any]],
    *,
    conn: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Enrich existing ``sessions.list`` rows without storing capabilities."""
    if not rows:
        return {"fields": list(SESSION_CONTROL_ROSTER_FIELDS), "rows": []}
    owned = conn is None
    if conn is None:
        from yoke_core.domain.db_helpers import connect

        conn = connect()
    try:
        identities = _identity_facts(
            conn,
            (str(row.get("session_id") or "") for row in rows),
        )
        worktrees = _active_worktrees(
            conn,
            (str(row.get("session_id") or "") for row in rows),
        )
        connected = connected_relay_routes(conn, now=now)
        projected = [
            _project_row(
                row,
                identity=identities.get(str(row.get("session_id") or ""), {}),
                connected_relays=connected,
                worktree=worktrees.get(str(row.get("session_id") or "")),
            )
            for row in rows
        ]
    finally:
        if owned:
            conn.close()
    return {"fields": list(SESSION_CONTROL_ROSTER_FIELDS), "rows": projected}


__all__ = ["SESSION_CONTROL_ROSTER_FIELDS", "session_control_roster_result"]
