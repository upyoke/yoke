"""One work item's execution posture, lanes, proof, and content index.

The read answers what the item *is* on every call and serves the item's
content — the stored narrative fields, the body rendered from them, the
Progress Log — only to a caller that names the section it wants. What every
caller gets instead is :mod:`yoke_core.domain.item_content_index`'s map of
which content exists and the exact command that returns each piece, so the
common read stays small and the reader can still find the rest.
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from yoke_contracts.public_ref import format_item_ref
from yoke_contracts.merge_queue_status import render_merge_queue_status
from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain.deployment_item_flow_resolution import item_completion_flow
from yoke_core.domain.file_budget_paths import extract_file_budget_paths
from yoke_core.domain.field_note_dash_promotion import (
    source_field_note_for_dash,
)
from yoke_core.domain.gate_satisfier_stamp import read_rungs
from yoke_core.domain.item_content_index import build_content_index
from yoke_core.domain.item_page_claims import active_item_claims
from yoke_core.domain.item_detail_qa import qa_plan_attachments, qa_rows
from yoke_core.domain.item_terminal_resources import terminal_stage_ids
from yoke_core.domain.item_worktrees import list_item_worktrees
from yoke_core.domain.render_body import build_body
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.workflow_behavior import worktree_lane_policy
from yoke_core.domain.workflow_effective_policies import (
    resolve_effective_workflow_policies,
)
from yoke_core.domain.workflow_runtime import workflow_runtime_from_row
from yoke_contracts.public_ref import ITEM_NOT_FOUND

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

_MERGE_QUEUE_COLUMNS = (
    "merge_queue_pr_number",
    "merge_queue_enqueued_at",
    "merge_queue_landed_at",
    "merge_queue_notified_at",
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _merge_queue_projection(conn: Any) -> str:
    """Project queue fields as NULL while an older control plane rolls out."""
    return ", ".join(
        f"i.{column}" if _column_exists(conn, "items", column) else f"NULL AS {column}"
        for column in _MERGE_QUEUE_COLUMNS
    )


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


def get_item_detail(
    item_id: int, *, include: Sequence[str] = ()
) -> dict[str, Any]:
    """Return the item's posture and proof, plus the content sections named.

    ``include`` names sections from
    :data:`~yoke_core.domain.item_content_index.DETAIL_INCLUDE_SECTIONS`; the
    caller's handler validates the names. Sections not named are reported in
    ``content_index`` with the read that returns them rather than served here.
    """
    wanted = set(include)
    conn = db_helpers.connect()
    try:
        marker = _p(conn)
        columns = ", ".join(f"i.{field}" for field in _NARRATIVE_FIELDS)
        queue_columns = _merge_queue_projection(conn)
        row = _dict_row(
            conn.execute(
                "SELECT i.id, i.title, i.status, i.priority, i.owner, "
                "i.blocked, i.blocked_reason, i.created_at, i.updated_at, "
                "i.deployment_flow, i.workflow_posture, "
                f"{queue_columns}, "
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
            raise LookupError(ITEM_NOT_FOUND)
        stored = {field: str(row.get(field) or "") for field in _NARRATIVE_FIELDS}
        # The body is rendered from the stored fields, so it is built only for
        # a caller that asked for it, or to source the File Budget when the
        # spec is empty and the body is the only place those paths can be.
        body = (
            build_body(conn, item_id) or ""
            if "body" in wanted or not stored["spec"]
            else ""
        )
        file_budget_paths = extract_file_budget_paths(stored["spec"] or body)
        narrative: dict[str, str] = {}
        if "narrative" in wanted:
            narrative.update(stored)
        if "body" in wanted:
            narrative["body"] = body
        progress_log = _progress_log(conn, item_id)
        public_ref = format_item_ref(
            row["project"], row["public_item_prefix"], row["project_sequence"]
        )
        claim = active_item_claims(conn, [item_id]).get(item_id)
        qa_requirements = qa_rows(conn, item_id)
        return {
            "id": int(row["id"]),
            "public_ref": public_ref,
            "title": str(row["title"]),
            "status": str(row["status"]),
            "priority": str(row.get("priority") or ""),
            "owner": str(row.get("owner") or ""),
            "blocked": bool(int(row.get("blocked") or 0)),
            "blocked_reason": str(row.get("blocked_reason") or ""),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "deployment_flow": row.get("deployment_flow"),
            "completion_flow": item_completion_flow(conn, item_id),
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
            "content_index": build_content_index(
                public_ref, narrative=stored, progress_log=progress_log
            ),
            "progress_log": (
                progress_log if "progress_log" in wanted else None
            ),
            "source_field_note": source_field_note_for_dash(conn, item_id),
            "qa_requirements": qa_requirements,
            "gate_satisfactions": read_rungs(conn, item_id),
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
