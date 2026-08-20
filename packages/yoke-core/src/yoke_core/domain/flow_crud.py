"""CRUD operations for deployment flows.

Public callable surface invoked by the front-door CLI in
:mod:`yoke_core.domain.flow` and by the ``db_router flows`` namespace.
"""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.db_helpers import (
    query_one,
    query_rows,
    query_scalar,
)
from yoke_core.domain.flow_validation import validate_stages
from yoke_core.domain.deployment_flow_state import (
    FLOW_STATUS_ACTIVE,
    assert_flow_definition_mutable,
    lock_deployment_flow_rows,
    validate_flow_status,
)
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
    rollback_workflow_binding_write_errors,
)

_FLOW_FIELDS = frozenset(
    {
        "id",
        "project",
        "name",
        "description",
        "stages",
        "on_failure",
        "created_at",
        "target_tier",
        "target_environment",
        "done_description",
        "status",
    }
)

_SELECT_COLS = (
    "df.id, p.slug AS project, df.name, df.description, df.stages, "
    "df.on_failure, df.created_at, df.target_tier, e.name AS target_environment, "
    "df.done_description, df.status"
)


def _format_row(row) -> str:
    return "|".join("" if v is None else str(v) for v in tuple(row))


def cmd_target(conn, flow_id: str) -> str:
    """Return ``tier|environment`` for one flow."""
    row = query_one(
        conn,
        "SELECT COALESCE(df.target_tier, ''), COALESCE(e.name, '') "
        "FROM deployment_flows df "
        "LEFT JOIN environments e ON e.id = df.target_environment_id "
        "WHERE df.id=%s",
        (flow_id,),
    )
    if row is None:
        raise LookupError(f"deployment flow '{flow_id}' not found")
    return _format_row(row)


def cmd_get(conn, flow_id: str, field: Optional[str] = None) -> str:
    if field:
        if field not in _FLOW_FIELDS:
            raise ValueError(f"invalid field '{field}'")
        exists = query_scalar(
            conn, "SELECT COUNT(*) FROM deployment_flows WHERE id=%s", (flow_id,)
        )
        if not exists:
            raise LookupError(f"deployment flow '{flow_id}' not found")
        if field == "project":
            val = query_scalar(
                conn,
                "SELECT p.slug FROM deployment_flows df "
                "JOIN projects p ON p.id = df.project_id "
                "WHERE df.id=%s",
                (flow_id,),
            )
        elif field == "target_environment":
            val = query_scalar(
                conn,
                "SELECT e.name FROM deployment_flows df "
                "LEFT JOIN environments e ON e.id=df.target_environment_id "
                "WHERE df.id=%s",
                (flow_id,),
            )
        else:
            val = query_scalar(
                conn, f"SELECT {field} FROM deployment_flows WHERE id=%s", (flow_id,)
            )
        return "" if val is None else str(val)
    else:
        row = query_one(
            conn,
            f"SELECT {_SELECT_COLS} FROM deployment_flows df "
            "JOIN projects p ON p.id = df.project_id "
            "LEFT JOIN environments e ON e.id=df.target_environment_id "
            "WHERE df.id=%s",
            (flow_id,),
        )
        if row is None:
            raise LookupError(f"deployment flow '{flow_id}' not found")
        return _format_row(row)


def cmd_list(
    conn,
    project: Optional[str] = None,
    *,
    include_disabled: bool = False,
) -> str:
    status_clause = "" if include_disabled else " AND df.status='active'"
    if project:
        ident = resolve_project(conn, project)
        assert ident is not None
        rows = query_rows(
            conn,
            f"SELECT {_SELECT_COLS} FROM deployment_flows df "
            "JOIN projects p ON p.id = df.project_id "
            "LEFT JOIN environments e ON e.id=df.target_environment_id "
            f"WHERE df.project_id=%s{status_clause} ORDER BY df.id ASC",
            (ident.id,),
        )
    else:
        rows = query_rows(
            conn,
            f"SELECT {_SELECT_COLS} FROM deployment_flows df "
            "JOIN projects p ON p.id = df.project_id "
            "LEFT JOIN environments e ON e.id=df.target_environment_id "
            f"WHERE 1=1{status_clause} ORDER BY df.id ASC",
        )
    return "\n".join(_format_row(row) for row in rows)


def cmd_stages(conn, flow_id: str) -> str:
    val = query_scalar(
        conn, "SELECT stages FROM deployment_flows WHERE id=%s", (flow_id,)
    )
    if val is None:
        raise LookupError(f"deployment flow '{flow_id}' not found")
    return val


def cmd_update_stages(
    conn,
    flow_id: str,
    stages_json: str,
    description: Optional[str] = None,
) -> str:
    """Replace a flow's stage list (and optionally its description).

    Validates the new stages against the executor/kind vocabularies and
    the project's migration-model cross-reference before writing, so a
    live flow row can never hold an undispatchable stage shape.
    """
    validate_stages(stages_json)
    locked = lock_deployment_flow_rows(
        conn,
        (flow_id,),
        binding=False,
    )
    flow = locked.get(flow_id)
    if flow is None:
        raise LookupError(f"deployment flow '{flow_id}' not found")
    assert_flow_definition_mutable(conn, flow_id)
    conn.execute(
        "UPDATE deployment_flows SET stages=%s WHERE id=%s",
        (stages_json, flow_id),
    )
    if description is not None:
        conn.execute(
            "UPDATE deployment_flows SET description=%s WHERE id=%s",
            (description, flow_id),
        )
    conn.commit()
    return f"Updated stages for deployment flow: {flow_id}"


def cmd_describe(conn, flow_id: str, description: str) -> str:
    """Rewrite a flow's human description without touching its stages.

    The definition-immutability guard exists so that an executed run's
    history can never be reinterpreted, which is a property of the stage
    list. A description is documentation about the flow, carries no
    dispatch semantics, and stays correctable for the life of the flow —
    otherwise the first run would freeze a flow's prose permanently and
    operators could never fix a description that turned out to mislead.
    """
    locked = lock_deployment_flow_rows(conn, (flow_id,), binding=False)
    if locked.get(flow_id) is None:
        raise LookupError(f"deployment flow '{flow_id}' not found")
    conn.execute(
        "UPDATE deployment_flows SET description=%s WHERE id=%s",
        (description, flow_id),
    )
    conn.commit()
    return f"Updated description for deployment flow: {flow_id}"


def cmd_set_status(conn, flow_id: str, status: str) -> str:
    """Enable or disable a flow without removing its definition or history."""
    normalized = validate_flow_status(status)
    exists = query_scalar(
        conn, "SELECT 1 FROM deployment_flows WHERE id=%s", (flow_id,)
    )
    if exists is None:
        raise LookupError(f"deployment flow '{flow_id}' not found")
    conn.execute(
        "UPDATE deployment_flows SET status=%s WHERE id=%s",
        (normalized, flow_id),
    )
    conn.commit()
    return f"Deployment flow '{flow_id}' is now {normalized}"


@rollback_workflow_binding_write_errors
def cmd_delete(conn, flow_id: str, repoint_items_to: Optional[str] = None) -> str:
    """Delete a flow; optionally repoint items that referenced it first.

    Refuses when items still reference the flow and no ``repoint_items_to``
    target was given, so a flow retirement never leaves silent dangling
    ``items.deployment_flow`` references.
    """
    flow_ids = (flow_id, repoint_items_to) if repoint_items_to else (flow_id,)
    locked_flows = lock_deployment_flow_rows(conn, flow_ids, binding=False)
    if flow_id not in locked_flows:
        raise LookupError(f"deployment flow '{flow_id}' not found")
    assert_flow_definition_mutable(conn, flow_id)

    referencing_rows = query_rows(
        conn,
        "SELECT id, project_id FROM items WHERE deployment_flow=%s ORDER BY id",
        (flow_id,),
    )
    referencing_ids = tuple(
        int(row["id"]) if hasattr(row, "keys") else int(row[0])
        for row in referencing_rows
    )
    referencing_projects = {
        int(row["project_id"] if hasattr(row, "keys") else row[1])
        for row in referencing_rows
    }
    lock_item_workflow_bindings(conn, referencing_ids)
    referencing = len(referencing_ids)
    repointed = 0
    if referencing:
        if not repoint_items_to:
            raise ValueError(
                f"{referencing} item(s) still reference flow '{flow_id}'; "
                "pass --repoint-items-to <flow-id> to retarget them"
            )
        if repoint_items_to == flow_id:
            raise ValueError("repoint target must differ from the deleted flow")
        target = locked_flows.get(repoint_items_to)
        if target is None or target[1] != FLOW_STATUS_ACTIVE:
            raise LookupError(
                f"active repoint target flow '{repoint_items_to}' not found"
            )
        source_project_id = int(locked_flows[flow_id][0])
        target_project_id = int(target[0])
        if target_project_id != source_project_id:
            raise ValueError("repoint target must belong to the deleted flow's project")
        if referencing_projects != {source_project_id}:
            raise ValueError(
                "referencing items do not all belong to the deleted flow's project"
            )
        conn.execute(
            "UPDATE items SET deployment_flow=%s WHERE deployment_flow=%s",
            (repoint_items_to, flow_id),
        )
        repointed = int(referencing)

    conn.execute("DELETE FROM deployment_flows WHERE id=%s", (flow_id,))
    conn.commit()
    suffix = (
        f" ({repointed} item(s) repointed to '{repoint_items_to}')" if repointed else ""
    )
    return f"Deleted deployment flow '{flow_id}'{suffix}"
