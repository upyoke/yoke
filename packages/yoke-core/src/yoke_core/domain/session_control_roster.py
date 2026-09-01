"""Read-time enrichment for the operator fleet-session roster."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping

from yoke_contracts.session_control.roster import (
    SESSION_CONTROL_ROSTER_DISPLAY_FIELDS,
)
from yoke_contracts.session_control.surface_versions import (
    machine_wake_surface,
)
from yoke_contracts.session_control.wake_delivery import (
    WAKE_ATTEMPT_ROSTER_RESULTS,
    wake_roster_state,
)
from yoke_core.domain import db_backend
from yoke_core.domain.session_list_fields import SESSION_LIST_FIELDS
from yoke_core.domain.session_control_diagnostics import session_diagnostics
from yoke_core.domain.session_control_health_facts import session_health_facts
from yoke_core.domain.session_holdings_health import (
    HOLDINGS_HEALTH_GREEN,
    current_holdings_health_by_session,
)
from yoke_core.domain.sessions_steering_visibility import steering_visibility
from yoke_core.domain.session_message_routing import messageability
from yoke_core.domain.session_relay_machine_versions import (
    connected_relay_routes,
    surface_versions_for,
)
from yoke_core.domain.session_relay_types import WakeMode
from yoke_core.domain.session_relay_versions import wake_candidate_supported
from yoke_core.domain.work_claim_targets import scope_int_sql


SESSION_CONTROL_ROSTER_FIELDS = tuple(
    dict.fromkeys((*SESSION_LIST_FIELDS, *SESSION_CONTROL_ROSTER_DISPLAY_FIELDS))
)


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row_dict(row: Any) -> dict[str, Any]:
    return {str(key): row[key] for key in row.keys()}


def _machine_names(conn: Any) -> dict[str, str]:
    """Latest relay-reported hostname per machine, newest heartbeat first."""
    rows = conn.execute(
        "SELECT machine_id, hostname FROM session_relays "
        "WHERE hostname IS NOT NULL AND hostname <> '' "
        "ORDER BY connected_until DESC, relay_id"
    ).fetchall()
    names: dict[str, str] = {}
    for row in rows:
        machine_id = str(row["machine_id"] or "")
        hostname = str(row["hostname"] or "").strip()
        if machine_id and hostname and machine_id not in names:
            names[machine_id] = hostname
    return names


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
        "last_heartbeat,last_tool_call_at,ended_at,terminated_at,turn_posture,"
        "turn_posture_at,offer_envelope "
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
    return bool(
        wake_operation
        and machine_wake_surface(surface, versions, wake_operation) is not None
    )


def _active_worktrees(
    conn: Any,
    session_ids: Iterable[str],
) -> dict[str, str]:
    ids = tuple(dict.fromkeys(session_ids))
    if not ids:
        return {}
    marker = _marker(conn)
    epic_id = scope_int_sql(conn, "wc.scope", "epic_id")
    task_num = scope_int_sql(conn, "wc.scope", "task_num")
    item_id = scope_int_sql(conn, "wc.scope", "item_id")
    rows = conn.execute(
        "SELECT wc.session_id,"
        "COALESCE(task_lane.path,item_lane.path,'') AS worktree_path,"
        "COALESCE(task_lane.branch,item_lane.branch,'') AS worktree_branch "
        "FROM work_claims wc "
        "LEFT JOIN epic_tasks et ON wc.target_kind='epic_task' "
        f"AND et.epic_id={epic_id} AND et.task_num={task_num} "
        "LEFT JOIN item_worktrees task_lane ON task_lane.id=et.item_worktree_id "
        "AND task_lane.state='active' "
        "LEFT JOIN item_worktrees item_lane ON item_lane.id=("
        "SELECT iw.id FROM item_worktrees iw WHERE wc.target_kind='item' "
        f"AND iw.item_id={item_id} AND iw.state='active' "
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


def _resume_states(
    conn: Any,
    session_ids: Iterable[str],
) -> dict[str, str]:
    ids = tuple(dict.fromkeys(session_ids))
    if not ids:
        return {}
    marker = _marker(conn)
    result_markers = ",".join(marker for _ in WAKE_ATTEMPT_ROSTER_RESULTS)
    rows = conn.execute(
        "SELECT target_session_id,result_code FROM session_message_attempts "
        "WHERE target_session_id IN ("
        + ",".join(marker for _ in ids)
        + ") AND result_code IN ("
        + result_markers
        + ") ORDER BY started_at DESC,attempt_id DESC",
        (*ids, *sorted(WAKE_ATTEMPT_ROSTER_RESULTS)),
    ).fetchall()
    states: dict[str, str] = {}
    for row in rows:
        session_id = str(row[0])
        state = wake_roster_state(row[1])
        if state is not None and session_id not in states:
            states[session_id] = state
    return states


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
    machine_names: Mapping[str, str],
    worktree: str | None,
    resume_state: str | None,
    diagnostics: Mapping[str, Any],
    health: Mapping[str, Any],
    steering: Mapping[str, Any],
    holdings_health: str,
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
        "machine_name": machine_names.get(machine_id) or None,
        "turn_posture": merged.get("turn_posture") or "unknown",
        "resume_state": resume_state,
        "relay": "connected"
        if relay_connected
        else ("unavailable" if machine_id else ""),
        "messageability": routing,
        **diagnostics,
        **health,
        **steering,
        "current_holdings_health": holdings_health,
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
        resume_states = _resume_states(
            conn,
            (str(row.get("session_id") or "") for row in rows),
        )
        connected = connected_relay_routes(conn, now=now)
        names = _machine_names(conn)
        diagnostics = session_diagnostics(conn, rows, identities)
        health = session_health_facts(conn, rows, identities)
        steering = steering_visibility(conn, rows, now=now)
        holdings_health = current_holdings_health_by_session(
            conn, rows, identities, diagnostics, now=now
        )
        projected = [
            _project_row(
                row,
                identity=identities.get(str(row.get("session_id") or ""), {}),
                connected_relays=connected,
                machine_names=names,
                worktree=worktrees.get(str(row.get("session_id") or "")),
                resume_state=resume_states.get(str(row.get("session_id") or "")),
                diagnostics=diagnostics.get(str(row.get("session_id") or ""), {}),
                health=health.get(str(row.get("session_id") or ""), {}),
                steering=steering.get(str(row.get("session_id") or ""), {}),
                holdings_health=holdings_health.get(
                    str(row.get("session_id") or ""),
                    HOLDINGS_HEALTH_GREEN,
                ),
            )
            for row in rows
        ]
    finally:
        if owned:
            conn.close()
    return {"fields": list(SESSION_CONTROL_ROSTER_FIELDS), "rows": projected}


__all__ = ["SESSION_CONTROL_ROSTER_FIELDS", "session_control_roster_result"]
