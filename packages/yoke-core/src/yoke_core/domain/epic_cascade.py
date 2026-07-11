"""Parent-status cascade for epic tasks.

Owns the cascade map, session-id resolution, project lookup, events emission,
and the cascade entrypoint. Re-exported from ``yoke_core.domain.epic`` for
patch-target compatibility so existing ``mock.patch("yoke_core.domain.epic.X")``
fixtures (notably patches on ``epic.cascade_task_status`` and ``epic._CASCADE_MAP``)
continue to intercept calls.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.epic_parsing import _now_iso, _placeholder
from yoke_core.domain.item_status_transitions import record_task_transition


# Cascade map: (from_parent, to_parent) -> (task_from, task_to)
_CASCADE_MAP = {
    # Forward cascades
    ("planning", "plan-drafted"): ("planning", "plan-drafted"),
    ("plan-drafted", "refining-plan"): ("plan-drafted", "refining-plan"),
    ("refining-plan", "planned"): ("refining-plan", "planned"),
    ("reviewed-implementation", "polishing-implementation"): ("reviewed-implementation", "polishing-implementation"),
    ("polishing-implementation", "implemented"): ("polishing-implementation", "implemented"),
    ("implemented", "release"): ("implemented", "release"),
    ("release", "done"): ("release", "done"),
    # Reverse cascades
    ("plan-drafted", "planning"): ("plan-drafted", "planning"),
    ("planned", "refining-plan"): ("planned", "refining-plan"),
    ("refining-plan", "plan-drafted"): ("refining-plan", "plan-drafted"),
    ("planned", "plan-drafted"): ("planned", "plan-drafted"),
    ("polishing-implementation", "reviewed-implementation"): ("polishing-implementation", "reviewed-implementation"),
    ("implemented", "polishing-implementation"): ("implemented", "polishing-implementation"),
    ("release", "implemented"): ("release", "implemented"),
    ("done", "release"): ("done", "release"),
}


def _resolve_session_id() -> str:
    return (
        os.environ.get("YOKE_SESSION_ID")
        or os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("CODEX_THREAD_ID")
        or f"{int(time.time())}-{os.getpid()}"
    )


def _cascade_project(conn, epic_id: str) -> str:
    try:
        numeric_epic_id = int(epic_id)
    except (TypeError, ValueError):
        return "yoke"

    row = query_one(
        conn,
        "SELECT COALESCE(p.slug, 'yoke') AS project "
        "FROM items i LEFT JOIN projects p ON p.id = i.project_id "
        f"WHERE i.id = {_placeholder(conn)} LIMIT 1",
        (numeric_epic_id,),
    )
    if row is None:
        return "yoke"
    return row["project"] or "yoke"


def _emit_task_status_changed(
    conn,
    *,
    session_id: str,
    project: str,
    epic_id: str,
    task_num: int,
    from_status: str,
    to_status: str,
    note: str,
) -> None:
    detail = {"from_status": from_status, "to_status": to_status}
    if note:
        detail["note"] = note

    event_time = _now_iso()
    envelope = {
        "event_id": str(uuid.uuid4()),
        "event_name": "TaskStatusChanged",
        "event_kind": "lifecycle",
        "event_type": "task_status_change",
        "event_time": event_time,
        "event_outcome": "completed",
        "source_type": "system",
        "severity": "STATUS",
        "session_id": session_id,
        "service": "cli",
        "project": project,
        "environment": None,
        "org_id": None,
        "actor": None,
        "agent": None,
        "item_id": str(epic_id),
        "task_num": task_num,
        "tool_name": None,
        "duration_ms": None,
        "exit_code": None,
        "trace_id": None,
        "parent_id": None,
        "anomaly_flags": None,
        "context": {"detail": detail},
    }

    p = _placeholder(conn)
    conn.execute(
        f"""
        INSERT INTO events (
          event_id, source_type, session_id, severity, event_kind,
          event_type, event_name, event_outcome, service, project,
          item_id, task_num, envelope
        ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        ON CONFLICT(event_id) DO NOTHING
        """,
        (
            envelope["event_id"],
            envelope["source_type"],
            envelope["session_id"],
            envelope["severity"],
            envelope["event_kind"],
            envelope["event_type"],
            envelope["event_name"],
            envelope["event_outcome"],
            envelope["service"],
            envelope["project"],
            envelope["item_id"],
            envelope["task_num"],
            json.dumps(envelope, separators=(",", ":")),
        ),
    )


def _emit_task_status_changed_best_effort(conn, **kwargs) -> None:
    """Emit cascade telemetry without rolling back the task status update."""
    try:
        conn.execute("SAVEPOINT epic_cascade_event")
        _emit_task_status_changed(conn, **kwargs)
        conn.execute("RELEASE SAVEPOINT epic_cascade_event")
    except db_backend.database_error_types(conn):
        try:
            conn.execute("ROLLBACK TO SAVEPOINT epic_cascade_event")
            conn.execute("RELEASE SAVEPOINT epic_cascade_event")
        except db_backend.database_error_types(conn):
            conn.rollback()


def cascade_task_status(
    conn,
    epic_id: str,
    from_parent: str,
    to_parent: str,
    *,
    scripts_dir: Optional[str] = None,
) -> str:
    """Cascade parent status change to eligible tasks.

    Returns the count of cascaded tasks as a string (e.g. "0", "3").
    """
    key = (from_parent, to_parent)
    if key not in _CASCADE_MAP:
        return "0"

    task_from, task_to = _CASCADE_MAP[key]

    rows = query_rows(
        conn,
        f"""SELECT task_num FROM epic_tasks
           WHERE epic_id={_placeholder(conn)} AND status={_placeholder(conn)}
           ORDER BY task_num ASC""",
        (str(epic_id), task_from),
    )

    if not rows:
        return "0"

    note = f"Parent cascade: {from_parent} -> {to_parent}"
    heartbeat = _now_iso()
    session_id = _resolve_session_id()
    project = _cascade_project(conn, epic_id)

    try:
        conn.execute("SELECT 1 FROM events LIMIT 1")
        emit_events = True
    except db_backend.database_error_types(conn):
        conn.rollback()
        emit_events = False

    p = _placeholder(conn)
    for row in rows:
        tnum = row["task_num"]
        try:
            conn.execute(
                f"UPDATE epic_tasks SET status = {p}, last_heartbeat = {p} WHERE epic_id = {p} AND task_num = {p}",
                (task_to, heartbeat, str(epic_id), tnum),
            )
        except db_backend.database_error_types(conn):
            conn.rollback()
            conn.execute(
                f"UPDATE epic_tasks SET status = {p} WHERE epic_id = {p} AND task_num = {p}",
                (task_to, str(epic_id), tnum),
            )

        record_task_transition(
            conn,
            epic_id=str(epic_id),
            task_num=tnum,
            from_status=task_from,
            to_status=task_to,
            source="epic-cascade",
            session_id=session_id or None,
        )

        if not emit_events:
            continue

        _emit_task_status_changed_best_effort(
            conn,
            session_id=session_id,
            project=project,
            epic_id=str(epic_id),
            task_num=tnum,
            from_status=task_from,
            to_status=task_to,
            note=note,
        )

    conn.commit()
    return str(len(rows))
