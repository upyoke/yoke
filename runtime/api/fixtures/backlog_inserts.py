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

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.project_identity import (
    DEFAULT_PUBLIC_ITEM_PREFIX,
    resolve_project,
)
from yoke_core.domain.project_seed_test_helpers import SEED_PROJECT_IDS
from yoke_core.domain.schema_common import _column_exists


def _now() -> str:
    return iso8601_now()


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _table_has_column(conn: Any, table: str, column: str) -> bool:
    try:
        return _column_exists(conn, table, column)
    except Exception:
        return False


def _ensure_project_id(conn: Any, project: str, *, ts: str) -> int:
    """Return numeric project authority, creating a lightweight row if needed."""
    ident = resolve_project(conn, project, required=False)
    if ident is not None:
        return ident.id
    slug = str(project)
    project_id = int(slug) if slug.isdigit() else SEED_PROJECT_IDS.get(slug)
    p = _placeholder(conn)
    if project_id is None:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM projects").fetchone()
        project_id = int(row[0])
    if slug.isdigit():
        slug = str(project_id)
    conn.execute(
        "INSERT INTO projects "
        "(id, slug, name, public_item_prefix, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}) "
        "ON CONFLICT (id) DO NOTHING",
        (
            project_id, slug, slug,
            DEFAULT_PUBLIC_ITEM_PREFIX, ts,
        ),
    )
    return project_id


def insert_item(
    conn: Any,
    *,
    id: int = 1,
    title: str = "Test item",
    type: str = "issue",
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
    cols = {
        "id": id,
        "title": title,
        "type": type,
        "status": status,
        "priority": priority,
        "created_at": ts,
        "updated_at": uts,
    }
    if _table_has_column(conn, "items", "project_id"):
        cols["project_id"] = extra.pop("project_id", _ensure_project_id(conn, project, ts=ts))
        cols["project_sequence"] = extra.pop("project_sequence", id)
    elif _table_has_column(conn, "items", "project"):
        cols["project"] = project
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
    cols = {
        "epic_id": epic_id,
        "task_num": task_num,
        "title": title,
        "status": status,
        "body": body,
        "dependencies": dependencies,
        **kwargs,
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
        cols["project_id"] = extra.pop("project_id", _ensure_project_id(conn, project, ts=ts))
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


def insert_qa_requirement(
    conn: Any,
    *,
    item_id: Optional[int] = 1,
    epic_id: Optional[int] = None,
    task_num: Optional[int] = None,
    deployment_run_id: Optional[str] = None,
    qa_kind: str = "smoke",
    qa_phase: str = "verification",
    blocking_mode: str = "blocking",
    requirement_source: str = "explicit",
    success_policy: Optional[str] = None,
    created_at: Optional[str] = None,
    **kwargs,
) -> Any:
    """Insert a row into ``qa_requirements`` and return it."""
    cols = {
        "item_id": item_id,
        "epic_id": epic_id,
        "task_num": task_num,
        "deployment_run_id": deployment_run_id,
        "qa_kind": qa_kind,
        "qa_phase": qa_phase,
        "blocking_mode": blocking_mode,
        "requirement_source": requirement_source,
        "success_policy": success_policy,
        "created_at": created_at or _now(),
        **kwargs,
    }
    col_names = ", ".join(cols.keys())
    p = _placeholder(conn)
    placeholders = ", ".join(p for _ in cols)
    cur = conn.execute(
        f"INSERT INTO qa_requirements ({col_names}) VALUES ({placeholders}) RETURNING id",
        tuple(cols.values()),
    )
    row_id = cur.fetchone()[0]
    conn.commit()
    return conn.execute(
        f"SELECT * FROM qa_requirements WHERE id = {p}", (row_id,)
    ).fetchone()


def insert_qa_run(
    conn: Any,
    *,
    qa_requirement_id: int = 1,
    executor_type: str = "pytest",
    qa_kind: str = "smoke",
    verdict: str = "pass",
    raw_result: Optional[str] = None,
    duration_ms: Optional[int] = None,
    created_at: Optional[str] = None,
    **kwargs,
) -> Any:
    """Insert a row into ``qa_runs`` and return it."""
    cols = {
        "qa_requirement_id": qa_requirement_id,
        "executor_type": executor_type,
        "qa_kind": qa_kind,
        "verdict": verdict,
        "raw_result": raw_result,
        "duration_ms": duration_ms,
        "created_at": created_at or _now(),
        **kwargs,
    }
    col_names = ", ".join(cols.keys())
    p = _placeholder(conn)
    placeholders = ", ".join(p for _ in cols)
    cur = conn.execute(
        f"INSERT INTO qa_runs ({col_names}) VALUES ({placeholders}) RETURNING id",
        tuple(cols.values()),
    )
    row_id = cur.fetchone()[0]
    conn.commit()
    return conn.execute(
        f"SELECT * FROM qa_runs WHERE id = {p}", (row_id,)
    ).fetchone()


__all__ = (
    "insert_item",
    "insert_epic_task",
    "insert_event",
    "insert_deployment_run",
    "insert_qa_requirement",
    "insert_qa_run",
)
