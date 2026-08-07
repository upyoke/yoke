"""Operator-authored execution instructions: resolution and row writes.

Instructions are global rows scoped by junction tables to workflows and
(optionally) projects. Resolution happens at read time: an item sees the
active instructions bound to its pinned workflow whose project scope
covers the item's project, ordered general-to-specific (all-projects
first, then project-scoped), with ``ordering`` as the tiebreak within a
group and ``id`` as the final deterministic tiebreak.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.workflow_execution_instructions_schema import (
    INSTRUCTION_PROJECTS_TABLE,
    INSTRUCTION_WORKFLOWS_TABLE,
    WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE,
)

INSTRUCTION_STATUSES = ("active", "disabled")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


class UnknownExecutionInstructionError(ValueError):
    """Raised when the requested instruction id has no row."""


class EmptyExecutionInstructionError(ValueError):
    """Raised when a write would leave a blank title or content."""


def resolve_execution_instructions(
    conn: Any, *, workflow_id: str, project_id: int
) -> List[Dict[str, Any]]:
    """Return the active instructions an item on this scope must obey."""
    p = _p(conn)
    rows = conn.execute(
        f"""
        SELECT i.id, i.title, i.content, i.applies_to_all_projects, i.ordering
        FROM {WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE} i
        JOIN {INSTRUCTION_WORKFLOWS_TABLE} w ON w.instruction_id = i.id
        WHERE i.status = 'active'
          AND w.workflow_id = {p}
          AND (i.applies_to_all_projects = 1 OR EXISTS (
              SELECT 1 FROM {INSTRUCTION_PROJECTS_TABLE} pr
              WHERE pr.instruction_id = i.id AND pr.project_id = {p}))
        ORDER BY i.applies_to_all_projects DESC, i.ordering, i.id
        """,
        (workflow_id, project_id),
    ).fetchall()
    return [
        {
            "id": row[0],
            "title": row[1],
            "content": row[2],
            "applies_to_all_projects": bool(row[3]),
            "ordering": row[4],
        }
        for row in rows
    ]


def resolve_for_item(conn: Any, item_id: int) -> List[Dict[str, Any]]:
    """Resolve instructions from an item's pinned workflow and project."""
    row = conn.execute(
        f"SELECT workflow_id, project_id FROM items WHERE id = {_p(conn)}",
        (item_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return []
    return resolve_execution_instructions(
        conn, workflow_id=str(row[0]), project_id=int(row[1])
    )


def _require_row(conn: Any, instruction_id: int) -> None:
    row = conn.execute(
        f"SELECT 1 FROM {WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE} "
        f"WHERE id = {_p(conn)}",
        (instruction_id,),
    ).fetchone()
    if row is None:
        raise UnknownExecutionInstructionError(
            f"no execution instruction with id {instruction_id}"
        )


def create_instruction(
    conn: Any,
    *,
    title: str,
    content: str,
    ordering: int = 0,
    status: str = "active",
    actor_id: Optional[int] = None,
) -> int:
    """Insert one instruction row (unscoped until set_instruction_scope)."""
    if not title.strip() or not content.strip():
        raise EmptyExecutionInstructionError(
            "execution instructions require a non-empty title and content"
        )
    now = iso8601_now()
    p = _p(conn)
    row = conn.execute(
        f"INSERT INTO {WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE} "
        "(title, content, applies_to_all_projects, ordering, status, "
        "updated_by_actor_id, created_at, updated_at) "
        f"VALUES ({p}, {p}, 0, {p}, {p}, {p}, {p}, {p}) RETURNING id",
        (title, content, ordering, status, actor_id, now, now),
    ).fetchone()
    return int(row[0])


def update_instruction(
    conn: Any,
    instruction_id: int,
    *,
    title: Optional[str] = None,
    content: Optional[str] = None,
    ordering: Optional[int] = None,
    status: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> None:
    """Update authored fields on one instruction; scope is separate."""
    _require_row(conn, instruction_id)
    p = _p(conn)
    updates: List[str] = []
    params: List[Any] = []
    for column, value in (
        ("title", title),
        ("content", content),
        ("ordering", ordering),
        ("status", status),
    ):
        if value is None:
            continue
        if column in ("title", "content") and not str(value).strip():
            raise EmptyExecutionInstructionError(
                f"execution instruction {column} cannot be blanked"
            )
        updates.append(f"{column} = {p}")
        params.append(value)
    if not updates:
        return
    updates.append(f"updated_by_actor_id = {p}")
    params.append(actor_id)
    updates.append(f"updated_at = {p}")
    params.append(iso8601_now())
    params.append(instruction_id)
    conn.execute(
        f"UPDATE {WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE} "
        f"SET {', '.join(updates)} WHERE id = {p}",
        tuple(params),
    )


def set_instruction_scope(
    conn: Any,
    instruction_id: int,
    *,
    workflow_ids: List[str],
    applies_to_all_projects: bool,
    project_ids: List[int],
    actor_id: Optional[int] = None,
) -> None:
    """Replace an instruction's workflow and project bindings.

    Project junction rows are retained even while the all-projects
    predicate is true — they are simply not consulted — so unchecking
    All restores the previously selected projects.
    """
    _require_row(conn, instruction_id)
    p = _p(conn)
    conn.execute(
        f"DELETE FROM {INSTRUCTION_WORKFLOWS_TABLE} "
        f"WHERE instruction_id = {p}",
        (instruction_id,),
    )
    for workflow_id in dict.fromkeys(workflow_ids):
        conn.execute(
            f"INSERT INTO {INSTRUCTION_WORKFLOWS_TABLE} "
            f"(instruction_id, workflow_id) VALUES ({p}, {p})",
            (instruction_id, workflow_id),
        )
    conn.execute(
        f"DELETE FROM {INSTRUCTION_PROJECTS_TABLE} "
        f"WHERE instruction_id = {p}",
        (instruction_id,),
    )
    for project_id in dict.fromkeys(project_ids):
        conn.execute(
            f"INSERT INTO {INSTRUCTION_PROJECTS_TABLE} "
            f"(instruction_id, project_id) VALUES ({p}, {p})",
            (instruction_id, project_id),
        )
    conn.execute(
        f"UPDATE {WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE} "
        f"SET applies_to_all_projects = {p}, updated_by_actor_id = {p}, "
        f"updated_at = {p} WHERE id = {p}",
        (
            1 if applies_to_all_projects else 0,
            actor_id,
            iso8601_now(),
            instruction_id,
        ),
    )


def list_instructions(conn: Any) -> List[Dict[str, Any]]:
    """Return every instruction with its scope, for editors and audits."""
    p = _p(conn)
    rows = conn.execute(
        f"""
        SELECT id, title, content, applies_to_all_projects, ordering,
               status, updated_by_actor_id, created_at, updated_at
        FROM {WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE}
        ORDER BY ordering, id
        """
    ).fetchall()
    instructions = []
    for row in rows:
        workflow_rows = conn.execute(
            f"SELECT workflow_id FROM {INSTRUCTION_WORKFLOWS_TABLE} "
            f"WHERE instruction_id = {p} ORDER BY workflow_id",
            (row[0],),
        ).fetchall()
        project_rows = conn.execute(
            f"SELECT project_id FROM {INSTRUCTION_PROJECTS_TABLE} "
            f"WHERE instruction_id = {p} ORDER BY project_id",
            (row[0],),
        ).fetchall()
        instructions.append(
            {
                "id": row[0],
                "title": row[1],
                "content": row[2],
                "applies_to_all_projects": bool(row[3]),
                "ordering": row[4],
                "status": row[5],
                "updated_by_actor_id": row[6],
                "created_at": row[7],
                "updated_at": row[8],
                "workflow_ids": [w[0] for w in workflow_rows],
                "project_ids": [p_row[0] for p_row in project_rows],
            }
        )
    return instructions


def delete_instruction(conn: Any, instruction_id: int) -> None:
    """Remove one instruction and its scope bindings."""
    _require_row(conn, instruction_id)
    p = _p(conn)
    conn.execute(
        f"DELETE FROM {INSTRUCTION_WORKFLOWS_TABLE} "
        f"WHERE instruction_id = {p}",
        (instruction_id,),
    )
    conn.execute(
        f"DELETE FROM {INSTRUCTION_PROJECTS_TABLE} "
        f"WHERE instruction_id = {p}",
        (instruction_id,),
    )
    conn.execute(
        f"DELETE FROM {WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE} "
        f"WHERE id = {p}",
        (instruction_id,),
    )
