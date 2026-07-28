"""Registry validation for ``items.deployment_flow`` writes."""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.deployment_flow_state import (
    FLOW_STATUS_ACTIVE,
    lock_deployment_flow_rows,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def normalize_deployment_flow_value(flow_id: Optional[str]) -> Optional[str]:
    """Normalize write sentinels before registry validation."""
    if flow_id == "null":
        return None
    return flow_id


def list_registered_flow_ids(conn: Any, project: Optional[str] = None) -> List[str]:
    """Return registered ``deployment_flows.id`` values, sorted.

    When ``project`` is provided, the result is filtered to flows
    belonging to that project. The list drives the operator-facing
    "registered alternatives" suffix on rejection messages.
    """
    if project:
        ident = resolve_project(conn, project, required=False)
        if ident is None:
            return []
        rows = conn.execute(
            f"SELECT id FROM deployment_flows WHERE project_id = {_p(conn)} ORDER BY id",
            (ident.id,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT id FROM deployment_flows ORDER BY id").fetchall()
    out: List[str] = []
    for row in rows:
        try:
            out.append(row["id"])
        except (TypeError, IndexError, KeyError):
            out.append(row[0])
    return out


def list_active_flow_ids(conn: Any, project: Optional[str] = None) -> List[str]:
    """Return active flow ids available for new item assignments."""
    if project:
        ident = resolve_project(conn, project, required=False)
        if ident is None:
            return []
        rows = conn.execute(
            f"SELECT id FROM deployment_flows WHERE project_id = {_p(conn)} "
            f"AND status = {_p(conn)} ORDER BY id",
            (ident.id, FLOW_STATUS_ACTIVE),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT id FROM deployment_flows WHERE status = {_p(conn)} ORDER BY id",
            (FLOW_STATUS_ACTIVE,),
        ).fetchall()
    return [str(row["id"] if hasattr(row, "keys") else row[0]) for row in rows]


def validate_and_lookup_flow_project(
    conn: Any,
    flow_id: Optional[str],
    project: Optional[str] = None,
    *,
    lock_binding: bool = False,
) -> Tuple[Optional[str], Optional[str]]:
    """Lookup-with-rejection for ``items.deployment_flow`` writes.

    Returns ``(flow_project, error)``:

    * ``(None, None)`` when ``flow_id`` is ``None``, ``"null"``, or the
      empty string. Empty / missing flow remains silently accepted;
      clearing the field is a deliberate operator action and the
      per-project gate runs elsewhere.
    * ``(flow_project, None)`` when ``flow_id`` is registered. The
      caller uses ``flow_project`` for the existing same-project gate.
    * ``(None, message)`` when ``flow_id`` is non-empty but missing from
      ``deployment_flows``. The message names the offending value and
      the registered alternatives so the operator's first move is to
      pick a real flow id.

    ``project`` only narrows the alternatives list in the error suffix;
    it does not alter the registered-flow check itself, so write paths
    that do not yet know the item project still surface the full
    registered list.
    """
    flow_id = normalize_deployment_flow_value(flow_id)
    if flow_id is None or flow_id == "":
        return None, None

    if lock_binding:
        locked = lock_deployment_flow_rows(conn, (flow_id,), binding=True).get(flow_id)
        row = None
        if locked is not None:
            project_row = conn.execute(
                f"SELECT slug FROM projects WHERE id = {_p(conn)}",
                (locked[0],),
            ).fetchone()
            if project_row is not None:
                project_slug = (
                    project_row["slug"]
                    if hasattr(project_row, "keys")
                    else project_row[0]
                )
                row = (project_slug, locked[1])
    else:
        row = conn.execute(
            "SELECT p.slug AS project, df.status FROM deployment_flows df "
            "JOIN projects p ON p.id = df.project_id "
            f"WHERE df.id = {_p(conn)}",
            (flow_id,),
        ).fetchone()
    if row is not None:
        status = str(row["status"] if hasattr(row, "keys") else row[1])
        if status != FLOW_STATUS_ACTIVE:
            flows = list_active_flow_ids(conn, project)
            suffix = (
                f" Active flows: {', '.join(flows)}."
                if flows
                else " No active deployment flows are registered."
            )
            return None, (
                f"deployment_flow '{flow_id}' is {status} and cannot be assigned."
                f"{suffix}"
            )
        try:
            return row["project"], None
        except (TypeError, IndexError, KeyError):
            return row[0], None

    flows = list_active_flow_ids(conn, project)
    if flows:
        if project:
            suffix = f" Registered flows for project '{project}': {', '.join(flows)}."
        else:
            suffix = f" Registered flows: {', '.join(flows)}."
    else:
        if project:
            suffix = f" No deployment flows are registered for project '{project}'."
        else:
            suffix = " No deployment flows are registered."
    return None, f"deployment_flow '{flow_id}' is not registered.{suffix}"


def require_flow_for_item_binding(
    conn: Any,
    flow_id: Optional[str],
    project: Optional[str] = None,
) -> Optional[str]:
    """Lock and validate a flow before inserting an item reference."""
    flow_project, error = validate_and_lookup_flow_project(
        conn, flow_id, project, lock_binding=True
    )
    if error:
        raise ValueError(error)
    if flow_project is not None and project:
        ident = resolve_project(conn, project, required=False)
        if ident is None or flow_project != ident.slug:
            raise ValueError(
                f"deployment flow '{flow_id}' belongs to project "
                f"'{flow_project}', not '{project}'"
            )
    return flow_project


__all__ = (
    "list_active_flow_ids",
    "list_registered_flow_ids",
    "normalize_deployment_flow_value",
    "require_flow_for_item_binding",
    "validate_and_lookup_flow_project",
)
