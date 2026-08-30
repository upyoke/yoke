"""Structured deployment-run presentation read for the universe UI."""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.deployment_run_carried_work import parse_carried_work
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.workflows_definition_read import _stage_names


RUN_PRESENTATION_FIELDS = (
    "member_items",
    "stages",
    "stage_index",
    "stage_count",
    "waiting_on_approval",
)


def _stage_rows(
    names: list[str],
    *,
    current: str,
    status: str,
) -> tuple[list[dict[str, str]], int]:
    current_index = names.index(current) if current in names else -1
    if names and (status == "succeeded" or current == "complete"):
        current_index = len(names) - 1
    rows: list[dict[str, str]] = []
    for index, name in enumerate(names):
        state = "pending"
        if status == "succeeded" or current == "complete":
            state = "complete"
        elif current_index >= 0 and index < current_index:
            state = "complete"
        elif current_index >= 0 and index == current_index:
            state = {
                "failed": "failed",
                "cancelled": "stopped",
                "executing": "active",
                "created": "active",
            }.get(status, "active")
        rows.append({"name": name, "state": state})
    return rows, current_index


def _member_items(
    conn: Any,
    run_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    if not run_ids:
        return {}
    markers = ", ".join("%s" for _ in run_ids)
    rows = conn.execute(
        "SELECT dri.run_id, i.id, i.title, i.status, i.project_sequence, "
        "p.id AS project_id, p.slug AS project, p.public_item_prefix "
        "FROM deployment_run_items dri "
        "JOIN items i ON i.id = dri.item_id "
        "JOIN projects p ON p.id = i.project_id "
        f"WHERE dri.run_id IN ({markers}) "
        "ORDER BY dri.run_id, i.id",
        tuple(run_ids),
    ).fetchall()
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        item_id = int(row["id"])
        result.setdefault(str(row["run_id"]), []).append(
            {
                "id": item_id,
                "ref": format_item_ref(
                    str(row["project"]),
                    str(row["public_item_prefix"] or ""),
                    int(row["project_sequence"]),
                ),
                "title": str(row["title"]),
                "status": str(row["status"]),
                "project_id": int(row["project_id"]),
                "project_sequence": int(row["project_sequence"]),
                "project": str(row["project"]),
            }
        )
    return result


def _pending_approvals(conn: Any, run_ids: list[str]) -> set[str]:
    if not run_ids:
        return set()
    clauses = " OR ".join("subject_key LIKE %s" for _ in run_ids)
    rows = conn.execute(
        "SELECT subject_key FROM decision_requests "
        "WHERE kind = 'deployment_stage_approval' "
        "AND subject_type = 'deployment_stage' AND status = 'pending' "
        f"AND ({clauses})",
        tuple(f"{run_id}:%" for run_id in run_ids),
    ).fetchall()
    return {str(row["subject_key"]).rsplit(":", 1)[0] for row in rows}


def list_deployment_runs(
    *,
    project: Optional[str],
    status: Optional[str],
    limit: int,
) -> list[dict[str, Any]]:
    """Return newest runs with member, stage, and approval relationships."""
    conn = connect()
    try:
        clauses: list[str] = []
        params: list[Any] = []
        if project:
            clauses.append("dr.project_id = %s")
            params.append(resolve_project_id(conn, project))
        if status:
            clauses.append("dr.status = %s")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        rows = conn.execute(
            "SELECT dr.id, p.slug AS project, dr.flow, dr.target_tier, "
            "e.name AS target_environment, "
            "dr.release_lineage, dr.status, dr.current_stage, dr.created_at, "
            "dr.started_at, dr.completed_at, dr.created_by, dr.carried_work, "
            "df.stages "
            "FROM deployment_runs dr "
            "JOIN projects p ON p.id = dr.project_id "
            "JOIN deployment_flows df ON df.id = dr.flow "
            "LEFT JOIN environments e ON e.id = dr.target_environment_id "
            f"{where}"
            "ORDER BY dr.created_at DESC, dr.id DESC LIMIT %s",
            (*params, limit),
        ).fetchall()
        base = [dict(row) for row in rows]
        run_ids = [str(row["id"]) for row in base]
        members = _member_items(conn, run_ids)
        pending = _pending_approvals(conn, run_ids)
        result: list[dict[str, Any]] = []
        for row in base:
            run_id = str(row["id"])
            row["carried_work"] = parse_carried_work(row.get("carried_work"))
            stage_names = _stage_names(row.pop("stages", None))
            stages, stage_index = _stage_rows(
                stage_names,
                current=str(row.get("current_stage") or ""),
                status=str(row.get("status") or ""),
            )
            result.append(
                {
                    **{
                        key: ("" if value is None else value)
                        for key, value in row.items()
                    },
                    "member_items": members.get(run_id, []),
                    "stages": stages,
                    "stage_index": stage_index,
                    "stage_count": len(stage_names),
                    "waiting_on_approval": run_id in pending,
                }
            )
        return result
    finally:
        conn.close()


__all__ = ["RUN_PRESENTATION_FIELDS", "list_deployment_runs"]
