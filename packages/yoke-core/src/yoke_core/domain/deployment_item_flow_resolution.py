"""Resolve an item's project and effective delivery flow."""

from yoke_core.domain import db_helpers
from yoke_core.domain import workflow_project_defaults
from yoke_core.domain.deployment_flow_state import FLOW_STATUS_ACTIVE
from yoke_core.domain.project_identity import resolve_project

NO_FLOW_HEAD = "has no deployment_flow; cannot start deploy run"


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


def describe_missing_flow(item_id: int, project: str) -> str:
    """Explain an unresolved delivery flow and name the way out of it.

    A run is attempted long after the filing that left the flow unset, so
    the refusal carries what it takes to get past it rather than only the
    fact that it stopped.
    """
    head = f"item {item_id} {NO_FLOW_HEAD}"
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
    "lookup_item_project_and_flow",
]
