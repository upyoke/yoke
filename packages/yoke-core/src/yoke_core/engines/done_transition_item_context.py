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


def load_done_item_context_over_transport(
    item_id: int,
) -> Optional[DoneItemContext]:
    """Load the done-transition item context through the connected transport.

    Relays ``done_transition.item_context`` so the item + pinned-workflow
    read runs over an https control plane as well as a local Postgres
    connection, then rebuilds the exact :class:`DoneItemContext` (including a
    fully reconstructed :class:`WorkflowRuntime`) the runner consumes.

    Returns ``None`` for a missing item — the runner's "item not found"
    branch. A read failure (transport unavailable, or an incomplete workflow
    pin surfaced by the handler) raises, aborting the transition exactly as
    the inline ``connect()`` + ``load_done_item_context`` did on a DB-level
    failure.
    """
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    resp = call_dispatcher(
        function_id="done_transition.item_context",
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload={},
    )
    if not resp.success:
        message = resp.error.message if resp.error else "unknown error"
        raise RuntimeError(f"done item context read failed: {message}")
    data = resp.result or {}
    if not data.get("found"):
        return None
    wf = data["workflow"]
    return DoneItemContext(
        title=str(data.get("title") or ""),
        stage_id=str(data.get("stage_id") or ""),
        lane_branch=str(data.get("lane_branch") or ""),
        project=str(data.get("project") or "yoke"),
        workflow=WorkflowRuntime(
            workflow_id=str(wf["workflow_id"]),
            workflow_version_id=int(wf["workflow_version_id"]),
            version=int(wf["version"]),
            definition_digest=str(wf["definition_digest"]),
            definition=wf["definition"],
        ),
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
    "load_done_item_context_over_transport",
]
