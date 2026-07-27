"""Backlog test fixture insert helpers.

Convenience helpers to insert rows into the disposable Postgres database
provided by the ``test_db`` fixture.  All helpers thread
:func:`yoke_core.domain.db_helpers.iso8601_now` through every
``created_at`` / ``updated_at`` column at insert time so callers do not
have to supply a timestamp.

``runtime.api.fixtures.backlog`` re-exports these helpers; tests should
import from that public fixture surface unless they specifically need this
implementation module.
"""

from __future__ import annotations

from typing import Any, Optional

from runtime.api.fixtures.backlog_insert_support import (
    ensure_project_id as _ensure_project_id,
    now as _now,
    placeholder as _placeholder,
    table_has_column as _table_has_column,
)
from runtime.api.fixtures.backlog_qa_inserts import (
    insert_qa_requirement,
    insert_qa_run,
)
from runtime.api.fixtures.workflow_pins import (
    current_workflow_pin_if_available,
)


def insert_item(
    conn: Any,
    *,
    id: int = 1,
    title: str = "Test item",
    workflow_id: str = "issue",
    status: str = "idea",
    priority: str = "medium",
    project: str = "yoke",
    created_at: Optional[str] = None,
    updated_at: Optional[str] = None,
    **kwargs,
) -> Any:
    """Insert a row into ``items`` and return it."""
    ts = created_at or _now()
    uts = updated_at or ts
    extra = dict(kwargs)
    schema_workflow_id = str(extra.pop("type", workflow_id))
    cols = {
        "id": id,
        "title": title,
        "status": status,
        "priority": priority,
        "created_at": ts,
        "updated_at": uts,
    }
    if _table_has_column(conn, "items", "type"):
        cols["type"] = schema_workflow_id
    if _table_has_column(conn, "items", "project_id"):
        cols["project_id"] = extra.pop(
            "project_id", _ensure_project_id(conn, project, ts=ts)
        )
        cols["project_sequence"] = extra.pop("project_sequence", id)
    elif _table_has_column(conn, "items", "project"):
        cols["project"] = project
    if (
        _table_has_column(conn, "items", "workflow_id")
        and "workflow_id" not in extra
        and "workflow_version_id" not in extra
    ):
        pin = current_workflow_pin_if_available(conn, schema_workflow_id)
        if pin is not None:
            pinned_workflow_id, workflow_version_id = pin
            cols["workflow_id"] = pinned_workflow_id
            cols["workflow_version_id"] = workflow_version_id
        else:
            cols["workflow_id"] = schema_workflow_id
    cols.update(extra)
    col_names = ", ".join(cols.keys())
    p = _placeholder(conn)
    placeholders = ", ".join(p for _ in cols)
    conn.execute(
        f"INSERT INTO items ({col_names}) VALUES ({placeholders})",
        tuple(cols.values()),
    )
    conn.commit()
    return conn.execute(f"SELECT * FROM items WHERE id = {p}", (id,)).fetchone()


def insert_item_worktree(
    conn: Any,
    *,
    item_id: int,
    branch: str,
    lane_role: str = "implementation",
    path: Optional[str] = None,
    state: str = "active",
    created_at: Optional[str] = None,
    updated_at: Optional[str] = None,
    released_at: Optional[str] = None,
    id: Optional[int] = None,
) -> Any:
    """Insert one universal item-owned worktree lane and return it."""
    ts = created_at or _now()
    cols = {
        "item_id": item_id,
        "branch": branch,
        "path": path,
        "lane_role": lane_role,
        "state": state,
        "created_at": ts,
        "updated_at": updated_at or ts,
        "released_at": released_at,
    }
    if id is not None:
        cols = {"id": id, **cols}
    p = _placeholder(conn)
    col_names = ", ".join(cols.keys())
    placeholders = ", ".join(p for _ in cols)
    row = conn.execute(
        f"INSERT INTO item_worktrees ({col_names}) "
        f"VALUES ({placeholders}) RETURNING id",
        tuple(cols.values()),
    ).fetchone()
    lane_id = int(row[0])
    conn.commit()
    return conn.execute(
        f"SELECT * FROM item_worktrees WHERE id = {p}",
        (lane_id,),
    ).fetchone()


def insert_epic_task(
    conn: Any,
    *,
    epic_id: int = 1,
    task_num: int = 1,
    title: str = "Test task",
    status: str = "planning",
    body: Optional[str] = None,
    dependencies: Optional[str] = None,
    **kwargs,
) -> Any:
    """Insert a row into ``epic_tasks`` and return it."""
    extra = dict(kwargs)
    if not _table_has_column(conn, "epic_tasks", "worktree"):
        branch = str(
            extra.pop("branch", None) or extra.pop("worktree", None) or ""
        ).strip()
        path = extra.pop("worktree_path", None)
        if branch and "item_worktree_id" not in extra:
            lane = insert_item_worktree(
                conn,
                item_id=int(epic_id),
                branch=branch,
                lane_role="worker",
                path=path,
            )
            extra["item_worktree_id"] = int(lane["id"])
    cols = {
        "epic_id": epic_id,
        "task_num": task_num,
        "title": title,
        "status": status,
        "body": body,
        "dependencies": dependencies,
        **extra,
    }
    col_names = ", ".join(cols.keys())
    p = _placeholder(conn)
    placeholders = ", ".join(p for _ in cols)
    conn.execute(
        f"INSERT INTO epic_tasks ({col_names}) VALUES ({placeholders})",
        tuple(cols.values()),
    )
    conn.commit()
    return conn.execute(
        f"SELECT * FROM epic_tasks WHERE epic_id = {p} AND task_num = {p}",
        (epic_id, task_num),
    ).fetchone()


def insert_event(
    conn: Any,
    *,
    event_id: str = "evt-test-001",
    event_name: str = "TestEvent",
    event_kind: str = "lifecycle",
    event_type: str = "test",
    source_type: str = "system",
    session_id: str = "sess-test",
    severity: str = "INFO",
    project: str = "yoke",
    envelope: Optional[str] = None,
    created_at: Optional[str] = None,
    **kwargs,
) -> Any:
    """Insert a row into ``events`` and return it."""
    ts = created_at or _now()
    extra = dict(kwargs)
    cols = {
        "event_id": event_id,
        "event_name": event_name,
        "event_kind": event_kind,
        "event_type": event_type,
        "source_type": source_type,
        "session_id": session_id,
        "severity": severity,
        "envelope": envelope,
        "created_at": ts,
    }
    if _table_has_column(conn, "events", "project_id"):
        cols["project_id"] = extra.pop(
            "project_id", _ensure_project_id(conn, project, ts=ts)
        )
    elif _table_has_column(conn, "events", "project"):
        cols["project"] = project
    cols.update(extra)
    col_names = ", ".join(cols.keys())
    p = _placeholder(conn)
    placeholders = ", ".join(p for _ in cols)
    cur = conn.execute(
        f"INSERT INTO events ({col_names}) VALUES ({placeholders}) RETURNING id",
        tuple(cols.values()),
    )
    row_id = cur.fetchone()[0]
    conn.commit()
    return conn.execute(f"SELECT * FROM events WHERE id = {p}", (row_id,)).fetchone()


def insert_deployment_run(
    conn: Any,
    *,
    id: str = "run-test-001",
    project: str = "yoke",
    flow: str = "flow-test",
    status: str = "created",
    current_stage: Optional[str] = None,
    created_at: Optional[str] = None,
    **kwargs,
) -> Any:
    """Insert a row into ``deployment_runs`` and return it.

    Ensures the referenced ``projects`` and ``deployment_flows`` rows exist.
    """
    ts = created_at or _now()
    p = _placeholder(conn)

    # Ensure project exists
    project_id = kwargs.pop("project_id", _ensure_project_id(conn, project, ts=ts))

    # Ensure flow exists
    existing = conn.execute(
        f"SELECT id FROM deployment_flows WHERE id = {p}", (flow,)
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO deployment_flows "
            "(id, project_id, name, stages, created_at) "
            f"VALUES ({p}, {p}, {p}, {p}, {p})",
            (flow, project_id, "test-flow", "[]", ts),
        )

    cols = {
        "id": id,
        "project_id": project_id,
        "flow": flow,
        "status": status,
        "current_stage": current_stage,
        "created_at": ts,
        **kwargs,
    }
    col_names = ", ".join(cols.keys())
    placeholders = ", ".join(p for _ in cols)
    conn.execute(
        f"INSERT INTO deployment_runs ({col_names}) VALUES ({placeholders})",
        tuple(cols.values()),
    )
    conn.commit()
    return conn.execute(
        f"SELECT * FROM deployment_runs WHERE id = {p}", (id,)
    ).fetchone()


__all__ = (
    "insert_item",
    "insert_epic_task",
    "insert_event",
    "insert_deployment_run",
    "insert_qa_requirement",
    "insert_qa_run",
)
