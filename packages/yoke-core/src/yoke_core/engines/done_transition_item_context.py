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


@dataclass(frozen=True)
class DoneItemContext:
    """Stable inputs loaded before delivery side effects begin."""

    title: str
    stage_id: str
    lane_branch: str
    project: str
    workflow: WorkflowRuntime


def load_done_item_context(
    conn: Any,
    item_id: int,
) -> Optional[DoneItemContext]:
    """Load an item plus its immutable workflow definition."""
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
        project=str(row["project"] or "yoke"),
        workflow=load_item_workflow_runtime(conn, item_id),
    )


def format_workflow_route(runtime: WorkflowRuntime) -> str:
    """Render the ordered route with its terminal stage highlighted."""
    return " -> ".join(
        f"[{stage_id}]"
        if stage_id == runtime.stage_ids[-1]
        else stage_id
        for stage_id in runtime.stage_ids
    )


__all__ = [
    "DoneItemContext",
    "format_workflow_route",
    "load_done_item_context",
]
