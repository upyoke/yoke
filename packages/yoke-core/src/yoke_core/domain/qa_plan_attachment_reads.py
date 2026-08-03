"""Attachment read model shared by QA plan catalog views."""

from __future__ import annotations

from typing import Any

from yoke_contracts.item_ref import format_item_ref
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.workflow_runtime import workflow_runtime_from_row


def plan_attachment_rows(conn: Any, plan_id: int) -> list[dict]:
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    project_defaults = query_rows(
        conn,
        "SELECT 'project_default' AS kind, p.slug AS project, "
        "d.workflow_id, d.transition_id, NULL AS item_id, "
        "v.id AS workflow_version_id, v.version, "
        "v.definition_json, v.definition_digest "
        "FROM qa_plan_project_defaults d "
        "JOIN projects p ON p.id=d.project_id "
        "JOIN workflows w ON w.id=d.workflow_id "
        "JOIN workflow_versions v ON v.id=w.current_version_id "
        f"WHERE d.plan_id={marker} "
        "ORDER BY p.slug, d.workflow_id, d.transition_id",
        (plan_id,),
    )
    item_attachments = query_rows(
        conn,
        "SELECT 'item' AS kind, p.slug AS project, "
        "i.workflow_id, a.transition_id, i.id AS item_id, "
        "p.public_item_prefix, i.project_sequence, "
        "v.id AS workflow_version_id, v.version, "
        "v.definition_json, v.definition_digest "
        "FROM qa_plan_item_attachments a "
        "JOIN items i ON i.id=a.item_id "
        "JOIN projects p ON p.id=i.project_id "
        "JOIN workflow_versions v ON v.id=i.workflow_version_id "
        f"WHERE a.plan_id={marker} "
        "ORDER BY p.slug, i.id, a.transition_id",
        (plan_id,),
    )
    result = []
    for raw in [*project_defaults, *item_attachments]:
        row = dict(raw)
        runtime = workflow_runtime_from_row(row)
        row["transition_label"] = runtime.stage_label(str(row["transition_id"]))
        for key in (
            "workflow_version_id",
            "version",
            "definition_json",
            "definition_digest",
        ):
            row.pop(key)
        if row["kind"] == "item":
            prefix = row.pop("public_item_prefix")
            sequence = row.pop("project_sequence")
            row["item_ref"] = format_item_ref(
                row["project"], prefix, sequence, item_id=int(row["item_id"])
            )
        result.append(row)
    return result


__all__ = ["plan_attachment_rows"]
