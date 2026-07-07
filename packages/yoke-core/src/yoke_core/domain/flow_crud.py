"""CRUD operations for deployment flows.

Public callable surface invoked by the front-door CLI in
:mod:`yoke_core.domain.flow` and by the ``db_router flows`` namespace.
"""
from __future__ import annotations

from typing import Optional

from yoke_core.domain.db_helpers import (
    iso8601_now, query_one, query_rows, query_scalar,
)
from yoke_core.domain.flow_cross_reference import (
    _validate_flow_stages_cross_reference,
)
from yoke_core.domain.flow_validation import validate_stages
from yoke_core.domain.project_identity import resolve_project

_FLOW_FIELDS = frozenset({
    "id", "project", "name", "description", "stages",
    "on_failure", "created_at", "target_env", "done_description",
})

_SELECT_COLS = (
    "df.id, p.slug AS project, df.name, df.description, df.stages, "
    "df.on_failure, df.created_at"
)


def _format_row(row) -> str:
    return "|".join("" if v is None else str(v) for v in tuple(row))


def cmd_create(conn, flow_id: str, project: str, name: str,
               description: str, stages_json: str,
               on_failure: str = "halt") -> str:
    validate_stages(stages_json)
    ident = resolve_project(conn, project)
    assert ident is not None
    _validate_flow_stages_cross_reference(conn, ident.id, stages_json, flow_id=None)
    conn.execute(
        "INSERT INTO deployment_flows "
        "(id, project_id, name, description, stages, on_failure, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (flow_id, ident.id, name, description, stages_json, on_failure,
         iso8601_now()),
    )
    conn.commit()
    return f"Created deployment flow: {flow_id}"


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
        else:
            val = query_scalar(
                conn, f"SELECT {field} FROM deployment_flows WHERE id=%s", (flow_id,)
            )
        return "" if val is None else str(val)
    else:
        row = query_one(
            conn,
            f"SELECT {_SELECT_COLS} FROM deployment_flows df "
            "JOIN projects p ON p.id = df.project_id WHERE df.id=%s",
            (flow_id,),
        )
        if row is None:
            raise LookupError(f"deployment flow '{flow_id}' not found")
        return _format_row(row)


def cmd_list(conn, project: Optional[str] = None) -> str:
    if project:
        ident = resolve_project(conn, project)
        assert ident is not None
        rows = query_rows(
            conn,
            f"SELECT {_SELECT_COLS} FROM deployment_flows df "
            "JOIN projects p ON p.id = df.project_id "
            "WHERE df.project_id=%s ORDER BY df.id ASC",
            (ident.id,),
        )
    else:
        rows = query_rows(
            conn,
            f"SELECT {_SELECT_COLS} FROM deployment_flows df "
            "JOIN projects p ON p.id = df.project_id ORDER BY df.id ASC",
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
    conn, flow_id: str, stages_json: str, description: Optional[str] = None,
) -> str:
    """Replace a flow's stage list (and optionally its description).

    Validates the new stages against the executor/kind vocabularies and
    the project's migration-model cross-reference before writing, so a
    live flow row can never hold an undispatchable stage shape.
    """
    validate_stages(stages_json)
    row = query_one(
        conn,
        "SELECT project_id FROM deployment_flows WHERE id=%s",
        (flow_id,),
    )
    if row is None:
        raise LookupError(f"deployment flow '{flow_id}' not found")
    _validate_flow_stages_cross_reference(
        conn, row[0], stages_json, flow_id=flow_id
    )
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


def cmd_delete(conn, flow_id: str, repoint_items_to: Optional[str] = None) -> str:
    """Delete a flow; optionally repoint items that referenced it first.

    Refuses when items still reference the flow and no ``repoint_items_to``
    target was given, so a flow retirement never leaves silent dangling
    ``items.deployment_flow`` references.
    """
    exists = query_scalar(
        conn, "SELECT 1 FROM deployment_flows WHERE id=%s", (flow_id,)
    )
    if exists is None:
        raise LookupError(f"deployment flow '{flow_id}' not found")

    referencing = query_scalar(
        conn,
        "SELECT COUNT(*) FROM items WHERE deployment_flow=%s",
        (flow_id,),
    ) or 0
    repointed = 0
    if referencing:
        if not repoint_items_to:
            raise ValueError(
                f"{referencing} item(s) still reference flow '{flow_id}'; "
                "pass --repoint-items-to <flow-id> to retarget them"
            )
        target = query_scalar(
            conn,
            "SELECT 1 FROM deployment_flows WHERE id=%s",
            (repoint_items_to,),
        )
        if target is None:
            raise LookupError(
                f"repoint target flow '{repoint_items_to}' not found"
            )
        conn.execute(
            "UPDATE items SET deployment_flow=%s WHERE deployment_flow=%s",
            (repoint_items_to, flow_id),
        )
        repointed = int(referencing)

    conn.execute("DELETE FROM deployment_flows WHERE id=%s", (flow_id,))
    conn.commit()
    suffix = (
        f" ({repointed} item(s) repointed to '{repoint_items_to}')"
        if repointed
        else ""
    )
    return f"Deleted deployment flow '{flow_id}'{suffix}"
