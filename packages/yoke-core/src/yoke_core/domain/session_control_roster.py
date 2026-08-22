"""Read-time enrichment for the operator fleet-session roster."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from yoke_contracts.session_control.roster import (
    SESSION_CONTROL_ROSTER_DISPLAY_FIELDS,
)
from yoke_core.domain import db_backend
from yoke_core.domain.session_list_fields import SESSION_LIST_FIELDS
from yoke_core.domain.session_message_routing import messageability


SESSION_CONTROL_ROSTER_FIELDS = tuple(
    dict.fromkeys((*SESSION_LIST_FIELDS, *SESSION_CONTROL_ROSTER_DISPLAY_FIELDS))
)


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _now_text(now: datetime | None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
        "SELECT session_id,executor_version,machine_id,last_heartbeat,"
        "last_tool_call_at,ended_at FROM harness_sessions WHERE session_id IN ("
        + ",".join(marker for _ in ids)
        + ")",
        ids,
    ).fetchall()
    return {str(row["session_id"]): _row_dict(row) for row in rows}


def _connected_machines(conn: Any, *, now: str) -> set[str]:
    marker = _marker(conn)
    rows = conn.execute(
        "SELECT DISTINCT machine_id FROM session_relays "
        f"WHERE state IN ('active','idle') AND connected_until>{marker}",
        (now,),
    ).fetchall()
    return {str(row["machine_id"]) for row in rows}


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
    connected_machines: set[str],
    worktree: str | None,
) -> dict[str, Any]:
    merged = {**row, **identity}
    machine_id = str(merged.get("machine_id") or "")
    relay_connected = bool(machine_id and machine_id in connected_machines)
    routing = messageability(
        merged,
        liveness=str(row.get("liveness") or "ended"),
    )
    routing["relay_connected"] = relay_connected
    routing["wake_available"] = bool(
        relay_connected and routing.get("wake_interface") != "none"
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
        connected = _connected_machines(conn, now=_now_text(now))
        projected = [
            _project_row(
                row,
                identity=identities.get(str(row.get("session_id") or ""), {}),
                connected_machines=connected,
                worktree=worktrees.get(str(row.get("session_id") or "")),
            )
            for row in rows
        ]
    finally:
        if owned:
            conn.close()
    return {"fields": list(SESSION_CONTROL_ROSTER_FIELDS), "rows": projected}


__all__ = ["SESSION_CONTROL_ROSTER_FIELDS", "session_control_roster_result"]
