"""Pinned workflow and item context for the done-transition runner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.item_worktree_resolution import (
    primary_item_worktree_branch_sql,
)
from yoke_core.domain.workflow_runtime import (
    WorkflowRuntime,
    load_item_workflow_runtime,
)
from yoke_core.domain.project_attribution import resolved_project


@dataclass(frozen=True)
class DoneItemContext:
    """Stable inputs loaded before delivery side effects begin."""

    title: str
    stage_id: str
    lane_branch: str
    project: str
    public_ref: str
    workflow: WorkflowRuntime


def load_done_item_context(
    conn: Any,
    item_id: int,
) -> Optional[DoneItemContext]:
    """Load an item plus its immutable workflow definition."""
    from yoke_core.domain.project_identity import render_item_ref

    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT i.title, i.status, "
        f"{primary_item_worktree_branch_sql('i.id')} AS lane_branch, "
        "p.slug AS project "
        "FROM items i LEFT JOIN projects p ON p.id = i.project_id "
        f"WHERE i.id = {placeholder}",
        (item_id,),
    ).fetchone()
    if row is None or not row["title"]:
        return None
    return DoneItemContext(
        title=str(row["title"]),
        stage_id=str(row["status"] or ""),
        lane_branch=str(row["lane_branch"] or ""),
        project=resolved_project(row["project"]),
        public_ref=render_item_ref(conn, item_id),
        workflow=load_item_workflow_runtime(conn, item_id),
    )


def done_item_context_from_payload(data: dict[str, Any]) -> DoneItemContext:
    """Decode a successful immutable context receipt in one place."""
    wf = data["workflow"]
    return DoneItemContext(
        title=str(data.get("title") or ""),
        stage_id=str(data.get("stage_id") or ""),
        lane_branch=str(data.get("lane_branch") or ""),
        project=resolved_project(data.get("project")),
        public_ref=str(data.get("public_ref") or ""),
        workflow=WorkflowRuntime(
            workflow_id=str(wf["workflow_id"]),
            workflow_version_id=int(wf["workflow_version_id"]),
            version=int(wf["version"]),
            definition_digest=str(wf["definition_digest"]),
            definition=wf["definition"],
        ),
    )
