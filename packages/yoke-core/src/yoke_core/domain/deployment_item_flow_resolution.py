"""Resolve an item's project and effective delivery flow."""

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain import db_helpers
from yoke_core.domain import workflow_project_defaults
from yoke_core.domain.deployment_flow_state import FLOW_STATUS_ACTIVE
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.workflow_project_defaults import WorkflowProjectDefaultError

NO_FLOW_HEAD = "has no deployment_flow; cannot start deploy run"


def item_completion_flow(conn: Any, item_id: int) -> str:
    """The flow that may close this item: explicit pin, else project default.

    Membership can carry the item on another same-project run. Completion,
    QA source obligations, and done-transition evidence all key off this
    flow — never the newest carrying run of any flow.
    """
    if not _column_exists(conn, "items", "deployment_flow"):
        return ""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    has_workflow = _column_exists(conn, "items", "workflow_id")
    columns = "i.deployment_flow, p.slug"
    if has_workflow:
        columns += ", i.workflow_id"
    row = conn.execute(
        f"SELECT {columns} "
        "FROM items i LEFT JOIN projects p ON p.id = i.project_id "
        f"WHERE i.id = {marker}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return ""
    explicit = row["deployment_flow"] if hasattr(row, "keys") else row[0]
    pinned = str(explicit or "").strip()
    if pinned:
        return pinned
    if not has_workflow:
        return ""
    project = str((row["slug"] if hasattr(row, "keys") else row[1]) or "")
    workflow_id = str(
        (row["workflow_id"] if hasattr(row, "keys") else row[2]) or ""
    )
    if not project or not workflow_id:
        return ""
    if not _table_exists(conn, "project_structure"):
        return ""
    try:
        default = workflow_project_defaults.get_delivery_default(
            conn, project=project, workflow_id=workflow_id,
        )
    except WorkflowProjectDefaultError:
        return ""
    return str(default or "")


def freeze_item_completion_flow(conn: Any, item_id: int) -> str:
    """Pin the live default onto the item if it has no explicit flow.

    Membership is the last write before a run can ship the item, so the
    default that would close it is frozen here. A later project-default
    change cannot retarget completion authority for an already-admitted
    item.
    """
    if not _column_exists(conn, "items", "deployment_flow"):
        return ""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT deployment_flow FROM items WHERE id = {marker}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return ""
    pinned = str(
        (row["deployment_flow"] if hasattr(row, "keys") else row[0]) or ""
    ).strip()
    if pinned:
        return pinned
    flow = item_completion_flow(conn, int(item_id))
    if not flow:
        return ""
    conn.execute(
        f"UPDATE items SET deployment_flow = {marker} "
        f"WHERE id = {marker} AND COALESCE(deployment_flow, '') = ''",
        (flow, int(item_id)),
    )
    return flow


def lookup_item_project_and_flow(item_id: int) -> tuple:
    """Return project and item override or workflow delivery default."""
    conn = db_helpers.connect()
    try:
        row = conn.execute(
            "SELECT p.slug AS project, i.deployment_flow, i.workflow_id "
            "FROM items i "
            "LEFT JOIN projects p ON p.id = i.project_id WHERE i.id = %s",
            (item_id,),
        ).fetchone()
        if row is not None and not row[1] and row[0] and row[2]:
            return row[0], workflow_project_defaults.get_delivery_default(
                conn,
                project=str(row[0]),
                workflow_id=str(row[2]),
            )
    finally:
        conn.close()
    if row is None:
        return None, None
    return row[0], row[1]


def _selectable_flow_ids(conn, project_id: int) -> list:
    """Return the active flow ids this project can still deploy through."""
    rows = conn.execute(
        "SELECT id FROM deployment_flows "
        "WHERE project_id = %s AND status = %s ORDER BY id",
        (project_id, FLOW_STATUS_ACTIVE),
    ).fetchall()
    return [str(row[0]) for row in rows]


def describe_missing_flow(item_ref: str, project: str) -> str:
    """Explain an unresolved delivery flow and name the way out of it.

    A run is attempted long after the filing that left the flow unset, so
    the refusal carries what it takes to get past it rather than only the
    fact that it stopped. The caller passes the item's already-rendered
    reference; this read is about the project's flows, not identity.
    """
    head = f"{item_ref} {NO_FLOW_HEAD}"
    conn = db_helpers.connect()
    try:
        identity = resolve_project(conn, project, required=False)
        flows = _selectable_flow_ids(conn, identity.id) if identity else []
    except LookupError:
        return head
    finally:
        conn.close()
    if identity is None:
        return f"{head}: project {project!r} does not exist."
    if not flows:
        return (
            f"{head}: project {project!r} declares no delivery default for "
            "this item and has no active deployment flow to select. Declare "
            "a flow for the project, then set it as the workflow's delivery "
            "default or pass --flow."
        )
    return (
        f"{head}: project {project!r} declares no delivery default for this "
        f"item. Pass --flow with one of: {', '.join(flows)}."
    )


__all__ = [
    "NO_FLOW_HEAD",
    "describe_missing_flow",
    "freeze_item_completion_flow",
    "item_completion_flow",
    "lookup_item_project_and_flow",
]
