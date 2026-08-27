"""One work item's stored narrative, execution posture, lanes, and proof."""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.item_ref import format_item_ref
from yoke_contracts.merge_queue_status import render_merge_queue_status
from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain.file_budget_paths import extract_file_budget_paths
from yoke_core.domain.field_note_dash_promotion import (
    source_field_note_for_dash,
)
from yoke_core.domain.item_page_claims import active_item_claims
from yoke_core.domain.item_detail_qa import qa_plan_attachments, qa_rows
from yoke_core.domain.item_terminal_resources import terminal_stage_ids
from yoke_core.domain.item_worktrees import list_item_worktrees
from yoke_core.domain.render_body import build_body
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.workflow_behavior import worktree_lane_policy
from yoke_core.domain.workflow_effective_policies import (
    resolve_effective_workflow_policies,
)
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
    return list_item_worktrees(conn, item_id)


def _path_claims(conn: Any, item_id: int) -> dict[str, Any]:
    if not _table_exists(conn, "path_claims"):
        return {"total": 0, "states": {}}
    marker = _p(conn)
    rows = conn.execute(
        "SELECT state, COUNT(*) AS total FROM path_claims "
        f"WHERE owner_kind = 'item' AND owner_item_id = {marker} "
        "GROUP BY state ORDER BY state",
        (item_id,),
    ).fetchall()
    states = {str(row[0]): int(row[1]) for row in rows}
    return {"total": sum(states.values()), "states": states}


def _progress_log(conn: Any, item_id: int) -> dict[str, Any] | None:
    if not _table_exists(conn, "item_sections"):
        return None
    marker = _p(conn)
    row = _dict_row(
        conn.execute(
            "SELECT content, updated_at FROM item_sections "
            f"WHERE item_id = {marker} AND section_name = {marker}",
            (item_id, "Progress Log"),
        )
    )
    if row is None or not str(row.get("content") or "").strip():
        return None
    return {
        "content": str(row["content"]),
        "updated_at": row.get("updated_at"),
    }


def _workflow_model(row: dict[str, Any]) -> dict[str, Any]:
    runtime = workflow_runtime_from_row(row)
    policy = worktree_lane_policy(runtime)
    item_posture = json.loads(str(row.get("workflow_posture") or "{}"))
    effective = resolve_effective_workflow_policies(runtime, item_posture)
    stage_id = str(row["status"])
    stage_is_defined = runtime.stage_index(stage_id) is not None
    next_stage_id = runtime.next_stage_id(stage_id)
    return {
        "id": runtime.workflow_id,
        "name": str(row["workflow_name"]),
        "version": runtime.version,
        "version_id": runtime.workflow_version_id,
        "stage_id": stage_id,
        "stage_label": runtime.stage_label(stage_id),
        "skill_id": (runtime.skill_for_stage(stage_id) if stage_is_defined else None),
        "next_skill_id": (
            runtime.skill_for_stage(next_stage_id)
            if next_stage_id is not None
            else None
        ),
        "policies": dict(runtime.policies),
        "effective_policies": dict(effective.values),
        "item_posture": item_posture,
        "allowed_lane_roles": sorted(policy.allowed_roles),
        "required_lane_roles": sorted(policy.required_roles),
        "terminal_stage_ids": sorted(terminal_stage_ids(runtime)),
    }


def get_item_detail(item_id: int) -> dict[str, Any]:
    """Return one complete read model for the work-item detail screens."""
    conn = db_helpers.connect()
    try:
        marker = _p(conn)
        columns = ", ".join(f"i.{field}" for field in _NARRATIVE_FIELDS)
        row = _dict_row(
            conn.execute(
                "SELECT i.id, i.title, i.status, i.priority, i.owner, "
                "i.blocked, i.blocked_reason, i.created_at, i.updated_at, "
                "i.deployment_flow, i.workflow_posture, "
                "i.merge_queue_pr_number, i.merge_queue_enqueued_at, "
                "i.merge_queue_landed_at, i.merge_queue_notified_at, "
                f"{columns}, "
                "p.id AS project_id, p.slug AS project, p.name AS project_name, "
                "p.default_branch, p.public_item_prefix, i.project_sequence, "
                "w.name AS workflow_name, v.id AS workflow_version_id, "
                "v.workflow_id, v.version, v.definition_json, v.definition_digest "
                "FROM items i JOIN projects p ON p.id = i.project_id "
                "JOIN workflows w ON w.id = i.workflow_id "
                "JOIN workflow_versions v ON v.id = i.workflow_version_id "
                f"WHERE i.id = {marker}",
                (item_id,),
            )
        )
        if row is None:
            raise LookupError(f"item {item_id} not found")
        narrative = {field: str(row.get(field) or "") for field in _NARRATIVE_FIELDS}
        narrative["body"] = build_body(conn, item_id) or ""
        file_budget_paths = extract_file_budget_paths(
            narrative["spec"] or narrative["body"]
        )
        claim = active_item_claims(conn, [item_id]).get(item_id)
        qa_requirements = qa_rows(conn, item_id)
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
            "merge_queue": {
                "pr_number": str(row.get("merge_queue_pr_number") or ""),
                "enqueued_at": str(row.get("merge_queue_enqueued_at") or ""),
                "landed_at": str(row.get("merge_queue_landed_at") or ""),
                "notified_at": str(row.get("merge_queue_notified_at") or ""),
                "status": render_merge_queue_status(
                    row.get("merge_queue_enqueued_at"),
                    row.get("merge_queue_landed_at"),
                    item_status=row.get("status"),
                ),
            },
            "project": {
                "id": int(row["project_id"]),
                "slug": str(row["project"]),
                "name": str(row["project_name"]),
                "default_branch": str(row.get("default_branch") or "main"),
            },
            "workflow": _workflow_model(row),
            "claim": claim,
            "worktrees": _worktrees(conn, item_id),
            "path_claims": _path_claims(conn, item_id),
            "file_budget": {
                "total": len(file_budget_paths),
                "paths": file_budget_paths,
            },
            "narrative": narrative,
            "progress_log": _progress_log(conn, item_id),
            "source_field_note": source_field_note_for_dash(conn, item_id),
            "qa_requirements": qa_requirements,
            "qa_plan_attachments": qa_plan_attachments(
                conn,
                item_id=item_id,
                project_id=int(row["project_id"]),
                workflow_id=str(row["workflow_id"]),
                requirements=qa_requirements,
            ),
        }
    finally:
        conn.close()


__all__ = ["get_item_detail"]
