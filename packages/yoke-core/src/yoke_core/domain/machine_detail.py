"""Operator-facing detail projection for one registered machine."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.actors import actor_name
from yoke_core.domain.actor_project_visibility import actor_visible_project_ids
from yoke_core.domain.actors import ActorError
from yoke_contracts.harness_hook_approval import hook_approval
from yoke_core.domain.harness_machine_state import read_harness_machine_reports
from yoke_core.domain.machine_registry import MachineRecord, marker
from yoke_core.domain.overview_harness_hook_health import (
    harness_targets,
    session_identities,
)
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.session_relay_read import list_visible_relays
from yoke_core.domain.session_surface_policy import list_marks


def _sessions(conn: Any, machine_id: str, visible: set[int]) -> list[dict[str, Any]]:
    if not _table_exists(conn, "harness_sessions"):
        return []
    p = marker(conn)
    rows = conn.execute(
        "SELECT session_id,executor,executor_surface,executor_version,model,mode,"
        "workspace,project_id,offered_at,last_heartbeat,ended_at,episode_started_at,"
        "last_tool_call_at FROM harness_sessions "
        f"WHERE machine_id={p} ORDER BY offered_at DESC LIMIT 100",
        (machine_id,),
    ).fetchall()
    return [
        {
            "session_id": str(row[0]),
            "executor": str(row[1]),
            "surface": row[2],
            "version": row[3],
            "model": row[4],
            "mode": row[5],
            "workspace": str(row[6]),
            "project_id": int(row[7]),
            "offered_at": row[8],
            "last_seen_at": row[9],
            "ended_at": row[10],
            "episode_started_at": row[11],
            "last_tool_call_at": row[12],
        }
        for row in rows
        if int(row[7]) in visible
    ]


def _launches(conn: Any, machine_id: str, visible: set[int]) -> list[dict[str, Any]]:
    if not _table_exists(conn, "session_launches"):
        return []
    p = marker(conn)
    rows = conn.execute(
        "SELECT launch_id,project_id,requested_surface,selected_surface,state,"
        "created_at,completed_at,result_code,registered_session_id "
        "FROM session_launches "
        f"WHERE assigned_machine_id={p} OR "
        f"(assigned_machine_id IS NULL AND requested_machine_id={p}) "
        "ORDER BY created_at DESC LIMIT 50",
        (machine_id, machine_id),
    ).fetchall()
    return [
        {
            "launch_id": str(row[0]),
            "project_id": int(row[1]),
            "requested_surface": row[2],
            "selected_surface": row[3],
            "state": str(row[4]),
            "created_at": row[5],
            "completed_at": row[6],
            "result_code": row[7],
            "session_id": row[8],
        }
        for row in rows
        if int(row[1]) in visible
    ]


def _tokens(conn: Any, machine_id: str) -> dict[str, Any]:
    if not _table_exists(conn, "api_tokens"):
        return {"status": "unavailable", "active_count": 0, "last_used_at": None}
    p = marker(conn)
    rows = conn.execute(
        "SELECT status,created_at,last_used_at,revoked_at FROM api_tokens "
        f"WHERE machine_id={p} ORDER BY created_at DESC",
        (machine_id,),
    ).fetchall()
    active = [row for row in rows if str(row[0]) == "active"]
    return {
        "status": "active" if active else ("revoked" if rows else "missing"),
        "active_count": len(active),
        "last_used_at": rows[0][2] if rows else None,
        "created_at": rows[0][1] if rows else None,
        "revoked_at": rows[0][3] if rows else None,
    }


def _project_reports(
    reports: list[dict[str, Any]], project_id: int
) -> list[dict[str, Any]]:
    rows = []
    for report in reports:
        if report["project_id"] != project_id:
            continue
        row = dict(report)
        gate = hook_approval(str(report.get("harness_id") or ""))
        row["trust_surface"] = gate["trust_surface"] if gate else None
        rows.append(row)
    return rows


def _projects(
    conn: Any,
    ids: set[int],
    reports: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not ids:
        return []
    p = marker(conn)
    placeholders = ",".join(p for _ in ids)
    rows = conn.execute(
        f"SELECT id,slug,name FROM projects WHERE id IN ({placeholders}) ORDER BY slug",
        tuple(sorted(ids)),
    ).fetchall()
    return [
        {
            "id": int(row[0]),
            "slug": str(row[1]),
            "name": str(row[2] or row[1]),
            "checkout": next(
                (
                    entry["workspace"]
                    for entry in sessions
                    if entry["project_id"] == int(row[0]) and entry["workspace"]
                ),
                None,
            ),
            "hook_reports": _project_reports(reports, int(row[0])),
            "recovery": "Run /yoke onboard in this project checkout.",
        }
        for row in rows
    ]


def machine_detail(
    conn: Any, *, record: MachineRecord, actor_id: int
) -> dict[str, Any]:
    """Compose durable identity with the latest safe machine telemetry."""
    visible = set(actor_visible_project_ids(conn, actor_id))
    relays = [
        row
        for row in list_visible_relays(conn, actor_id=actor_id, limit=500)
        if row["machine_id"] == record.machine_id
    ]
    relay = relays[0] if relays else None
    sessions = _sessions(conn, record.machine_id, visible)
    launches = _launches(conn, record.machine_id, visible)
    reports = [
        row
        for row in read_harness_machine_reports(conn)
        if row["machine_id"] == record.machine_id and row["project_id"] in visible
    ]
    identities = session_identities(
        (
            row["executor"],
            row["surface"],
            0,
            row["episode_started_at"],
            row["last_tool_call_at"],
            row["last_seen_at"],
        )
        for row in sessions
    )
    project_ids = {row["project_id"] for row in sessions + launches}
    if relay:
        project_ids.update(relay.get("project_ids") or [])
    machine = record.to_dict()
    try:
        machine["owner"] = actor_name(conn, record.owner_actor_id)
    except ActorError:
        machine["owner"] = f"actor {record.owner_actor_id}"
    return {
        "machine": machine,
        "relay": relay,
        "harnesses": harness_targets(
            identities,
            reports,
            installed_surfaces=(relay or {}).get("surface_versions") or {},
        ),
        "projects": _projects(conn, project_ids, reports, sessions),
        "running_sessions": [row for row in sessions if row["ended_at"] is None],
        "recent_sessions": sessions[:20],
        "recent_launches": launches[:20],
        "surface_policies": list_marks(conn, machine_id=record.machine_id),
        "token": _tokens(conn, record.machine_id),
        "credential_presence": (relay or {}).get("credential_presence") or {},
    }


__all__ = ["machine_detail"]
