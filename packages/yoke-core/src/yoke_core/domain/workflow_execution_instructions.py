"""Operator-authored execution instructions: resolution and row writes.

Instructions are global rows scoped on two axes, workflows and projects,
each by an all-of-them predicate or explicit junction rows. Resolution
happens at read time: an item sees every instruction whose workflow scope
covers its pinned workflow and whose project scope covers its project,
ordered general-to-specific — broadest scope first, ``id`` as the final
deterministic tiebreak.

An instruction with no workflow scope reaches nothing, which is how an
instruction is taken out of use: there is no separate status flag that
could disagree with what an agent actually reads.
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


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


class UnknownExecutionInstructionError(ValueError):
    """Raised when the requested instruction id has no row."""


class EmptyExecutionInstructionError(ValueError):
    """Raised when a write would leave an instruction with no prose."""


def resolve_execution_instructions(
    conn: Any, *, workflow_id: str, project_id: int
) -> List[Dict[str, Any]]:
    """Return the instructions an item on this scope must obey."""
    p = _p(conn)
    rows = conn.execute(
        f"""
        SELECT i.id, i.content, i.applies_to_all_workflows,
               i.applies_to_all_projects
        FROM {WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE} i
        WHERE (i.applies_to_all_workflows = 1 OR EXISTS (
                  SELECT 1 FROM {INSTRUCTION_WORKFLOWS_TABLE} w
                  WHERE w.instruction_id = i.id AND w.workflow_id = {p}))
          AND (i.applies_to_all_projects = 1 OR EXISTS (
                  SELECT 1 FROM {INSTRUCTION_PROJECTS_TABLE} pr
                  WHERE pr.instruction_id = i.id AND pr.project_id = {p}))
        ORDER BY i.applies_to_all_workflows DESC,
                 i.applies_to_all_projects DESC, i.id
        """,
        (workflow_id, project_id),
    ).fetchall()
    return [
        {
            "id": row[0],
            "content": row[1],
            "applies_to_all_workflows": bool(row[2]),
            "applies_to_all_projects": bool(row[3]),
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
    content: str,
    actor_id: Optional[int] = None,
) -> int:
    """Insert one instruction row (unscoped until set_instruction_scope)."""
    if not content.strip():
        raise EmptyExecutionInstructionError(
            "an execution instruction requires non-empty content"
        )
    now = iso8601_now()
    p = _p(conn)
    row = conn.execute(
        f"INSERT INTO {WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE} "
        "(content, applies_to_all_workflows, applies_to_all_projects, "
        "updated_by_actor_id, created_at, updated_at) "
        f"VALUES ({p}, 0, 0, {p}, {p}, {p}) RETURNING id",
        (content, actor_id, now, now),
    ).fetchone()
    return int(row[0])


def update_instruction(
    conn: Any,
    instruction_id: int,
    *,
    content: str,
    actor_id: Optional[int] = None,
) -> None:
    """Rewrite one instruction's prose; scope is set separately."""
    _require_row(conn, instruction_id)
    if not content.strip():
        raise EmptyExecutionInstructionError(
            "execution instruction content cannot be blanked"
        )
    p = _p(conn)
    conn.execute(
        f"UPDATE {WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE} "
        f"SET content = {p}, updated_by_actor_id = {p}, updated_at = {p} "
        f"WHERE id = {p}",
        (content, actor_id, iso8601_now(), instruction_id),
    )


def set_instruction_scope(
    conn: Any,
    instruction_id: int,
    *,
    workflow_ids: List[str],
    applies_to_all_projects: bool,
    project_ids: List[int],
    applies_to_all_workflows: bool = False,
    actor_id: Optional[int] = None,
) -> None:
    """Replace an instruction's workflow and project bindings.

    Junction rows on either axis are retained even while that axis's
    all-of-them predicate is true — they are simply not consulted — so
    unchecking All restores the previous selection instead of discarding it.
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
        f"SET applies_to_all_workflows = {p}, applies_to_all_projects = {p}, "
        f"updated_by_actor_id = {p}, updated_at = {p} WHERE id = {p}",
        (
            1 if applies_to_all_workflows else 0,
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
        SELECT id, content, applies_to_all_workflows,
               applies_to_all_projects, updated_by_actor_id,
               created_at, updated_at
        FROM {WORKFLOW_EXECUTION_INSTRUCTIONS_TABLE}
        ORDER BY applies_to_all_workflows DESC,
                 applies_to_all_projects DESC, id
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
                "content": row[1],
                "applies_to_all_workflows": bool(row[2]),
                "applies_to_all_projects": bool(row[3]),
                "updated_by_actor_id": row[4],
                "created_at": row[5],
                "updated_at": row[6],
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
