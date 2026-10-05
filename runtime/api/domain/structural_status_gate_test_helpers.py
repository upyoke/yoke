"""Row builders for the definition-structure lifecycle gate tests.

The ``gate_conn`` fixture these take lives in this directory's conftest.
"""

from __future__ import annotations

from typing import Any


def insert_item(
    conn: Any,
    item_id: int,
    *,
    workflow: str,
    status: str,
    title: str = "Fixture item",
    spec: str = "",
) -> None:
    """Insert one item pinned to the workflow's current seeded version."""
    conn.execute(
        "INSERT INTO items (id, title, workflow_id, workflow_version_id, "
        "status, priority, project_id, project_sequence, created_at, "
        "updated_at, source, frozen) VALUES (%s, %s, %s, "
        "(SELECT current_version_id FROM workflows WHERE id = %s), %s, "
        "'medium', 1, %s, '2026-01-01', '2026-01-01', 'user', 0)",
        (item_id, title, workflow, workflow, status, item_id),
    )
    if spec:
        conn.execute("UPDATE items SET spec = %s WHERE id = %s", (spec, item_id))
    conn.commit()


def insert_dependency(
    conn: Any, dependent: int, blocking: int, gate_point: str, satisfaction: str
) -> None:
    conn.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item_id, blocking_item_id, gate_point, satisfaction, source, "
        "created_at) VALUES (%s, %s, %s, %s, 'operator', '2026-10-05')",
        (dependent, blocking, gate_point, satisfaction),
    )
    conn.commit()


def insert_task(conn: Any, epic_id: int, task_num: int, status: str) -> None:
    conn.execute(
        "INSERT INTO epic_tasks (epic_id, task_num, title, status) "
        "VALUES (%s, %s, %s, %s)",
        (epic_id, task_num, f"Task {task_num}", status),
    )
    conn.commit()


def runtime_for(conn: Any, item_id: int):
    from yoke_core.domain.workflow_runtime import load_item_workflow_runtime

    return load_item_workflow_runtime(conn, item_id)
