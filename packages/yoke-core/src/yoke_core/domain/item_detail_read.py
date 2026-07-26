"""One work item's stored narrative, execution posture, lanes, and proof."""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.item_ref import format_item_ref
from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain.item_page_claims import active_item_claims
from yoke_core.domain.render_body import build_body
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.workflow_behavior import worktree_lane_policy
from yoke_core.domain.workflow_runtime import workflow_runtime_from_row

_NARRATIVE_FIELDS = (
    "spec",
    "design_spec",
    "technical_plan",
    "worktree_plan",
    "shepherd_log",
    "shepherd_caveats",
    "test_results",
    "deploy_log",
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _dict_row(cursor: Any) -> dict[str, Any] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [str(column[0]) for column in cursor.description]
    return dict(row) if hasattr(row, "keys") else dict(zip(columns, row))


def _dict_rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [str(column[0]) for column in cursor.description]
    return [
        dict(row) if hasattr(row, "keys") else dict(zip(columns, row))
        for row in cursor.fetchall()
    ]


def _worktrees(conn: Any, item_id: int) -> list[dict[str, Any]]:
    if not _table_exists(conn, "item_worktrees"):
        return []
    marker = _p(conn)
    return _dict_rows(conn.execute(
        "SELECT id, session_id, branch, path, lane_role, state, "
        "created_at, updated_at, released_at FROM item_worktrees "
        f"WHERE item_id = {marker} ORDER BY id",
        (item_id,),
    ))


def _path_claims(conn: Any, item_id: int) -> dict[str, Any]:
    if not _table_exists(conn, "path_claims"):
        return {"total": 0, "states": {}}
    marker = _p(conn)
    rows = conn.execute(
        "SELECT state, COUNT(*) AS total FROM path_claims "
        f"WHERE item_id = {marker} GROUP BY state ORDER BY state",
        (item_id,),
    ).fetchall()
    states = {str(row[0]): int(row[1]) for row in rows}
    return {"total": sum(states.values()), "states": states}


def _progress_log(conn: Any, item_id: int) -> dict[str, Any] | None:
    if not _table_exists(conn, "item_sections"):
        return None
    marker = _p(conn)
    row = _dict_row(conn.execute(
        "SELECT content, updated_at FROM item_sections "
        f"WHERE item_id = {marker} AND section_name = {marker}",
        (item_id, "Progress Log"),
    ))
    if row is None or not str(row.get("content") or "").strip():
        return None
    return {
        "content": str(row["content"]),
        "updated_at": row.get("updated_at"),
    }


def _qa_rows(conn: Any, item_id: int) -> list[dict[str, Any]]:
    if not _table_exists(conn, "qa_requirements"):
        return []
    marker = _p(conn)
    return _dict_rows(conn.execute(
        "SELECT q.id, q.qa_kind, q.qa_phase, q.blocking_mode, "
        "q.requirement_source, q.success_policy, q.waived_at, q.created_at, "
        "r.id AS run_id, r.verdict, r.execution_status, r.completed_at "
        "FROM qa_requirements q "
        "LEFT JOIN qa_runs r ON r.id = ("
        "  SELECT MAX(latest.id) FROM qa_runs latest "
        "  WHERE latest.qa_requirement_id = q.id"
        ") "
        f"WHERE q.item_id = {marker} OR q.epic_id = {marker} "
        "ORDER BY q.id",
        (item_id, item_id),
    ))


def _workflow_model(row: dict[str, Any]) -> dict[str, Any]:
    runtime = workflow_runtime_from_row(row)
    policy = worktree_lane_policy(runtime)
    item_posture = json.loads(str(row.get("workflow_posture") or "{}"))
    stage_id = str(row["status"])
    stage = runtime.stage(stage_id) or {}
    stage_is_defined = runtime.stage_index(stage_id) is not None
    next_stage_id = runtime.next_stage_id(stage_id)
    return {
        "id": runtime.workflow_id,
        "name": str(row["workflow_name"]),
        "version": runtime.version,
        "version_id": runtime.workflow_version_id,
        "stage_id": stage_id,
        "stage_label": str(
            stage.get("label") or stage_id.replace("-", " ").title()
        ),
        "executor_id": (
            runtime.executor_for_stage(stage_id) if stage_is_defined else None
        ),
        "next_executor_id": (
            runtime.executor_for_stage(next_stage_id)
            if next_stage_id is not None else None
        ),
        "policies": dict(runtime.policies),
        "item_posture": item_posture,
        "allowed_lane_roles": sorted(policy.allowed_roles),
        "required_lane_roles": sorted(policy.required_roles),
    }


def get_item_detail(item_id: int) -> dict[str, Any]:
    """Return one complete read model for the work-item detail screens."""
    conn = db_helpers.connect()
    try:
        marker = _p(conn)
        columns = ", ".join(f"i.{field}" for field in _NARRATIVE_FIELDS)
        row = _dict_row(conn.execute(
            "SELECT i.id, i.title, i.status, i.priority, i.owner, "
            "i.blocked, i.blocked_reason, i.created_at, i.updated_at, "
            "i.deployment_flow, i.workflow_posture, "
            f"{columns}, "
            "p.id AS project_id, p.slug AS project, p.name AS project_name, "
            "p.public_item_prefix, i.project_sequence, "
            "w.name AS workflow_name, v.id AS workflow_version_id, "
            "v.workflow_id, v.version, v.definition_json, v.definition_digest "
            "FROM items i JOIN projects p ON p.id = i.project_id "
            "JOIN workflows w ON w.id = i.workflow_id "
            "JOIN workflow_versions v ON v.id = i.workflow_version_id "
            f"WHERE i.id = {marker}",
            (item_id,),
        ))
        if row is None:
            raise LookupError(f"item {item_id} not found")
        narrative = {
            field: str(row.get(field) or "") for field in _NARRATIVE_FIELDS
        }
        narrative["body"] = build_body(conn, item_id) or ""
        claim = active_item_claims(conn, [item_id]).get(item_id)
        return {
            "id": int(row["id"]),
            "public_ref": format_item_ref(
                row["project"],
                row["public_item_prefix"],
                row["project_sequence"],
                item_id=item_id,
            ),
            "title": str(row["title"]),
            "status": str(row["status"]),
            "priority": str(row.get("priority") or ""),
            "owner": str(row.get("owner") or ""),
            "blocked": bool(int(row.get("blocked") or 0)),
            "blocked_reason": str(row.get("blocked_reason") or ""),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "deployment_flow": row.get("deployment_flow"),
            "project": {
                "id": int(row["project_id"]),
                "slug": str(row["project"]),
                "name": str(row["project_name"]),
            },
            "workflow": _workflow_model(row),
            "claim": claim,
            "worktrees": _worktrees(conn, item_id),
            "path_claims": _path_claims(conn, item_id),
            "narrative": narrative,
            "progress_log": _progress_log(conn, item_id),
            "qa_requirements": _qa_rows(conn, item_id),
        }
    finally:
        conn.close()


__all__ = ["get_item_detail"]
