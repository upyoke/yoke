"""Resolve an item's project and effective delivery flow."""

from yoke_core.domain import db_helpers
from yoke_core.domain import workflow_project_defaults


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


__all__ = ["lookup_item_project_and_flow"]
