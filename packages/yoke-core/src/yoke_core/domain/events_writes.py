"""Insert and severity config/check helpers for the Yoke event platform.

Owns the row-level insert path (``cmd_insert``) plus the severity-config
read/write/check surface (``check_severity``, ``cmd_severity_config_set``,
``cmd_severity_config_list``, ``cmd_severity_check``). Schema DDL and
table init live in ``events_schema``; per-severity retention pruning
lives in ``events_prune``. Re-exports below preserve the public surface
for ``events_crud`` and other historical callers.

Imports of constants/helpers from ``events_crud`` happen lazily inside
each function. ``events_crud`` does a late re-export from this module
after defining its own helpers; binding ``events_crud`` symbols at
module top-level here would re-enter the partially-initialised
``events_crud`` whenever a caller imports ``events_writes`` directly,
which raises ``ImportError`` for the late-bound names. Function-local
imports break that cycle while preserving ``events_crud``'s late
re-export.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect, iso8601_now, query_rows, query_scalar
from yoke_core.domain.events_schema import _create_events_table, cmd_init
from yoke_core.domain.events_prune import cmd_prune
from yoke_core.domain.events_retired_name_guard import assert_event_name_not_retired
from yoke_core.domain.yok_n_parser import parse_item_id

__all__ = [
    "_create_events_table",
    "check_severity",
    "check_severity_conn",
    "cmd_init",
    "cmd_insert",
    "cmd_prune",
    "cmd_severity_check",
    "cmd_severity_config_list",
    "cmd_severity_config_set",
    "hook_emit_connection",
]


@contextmanager
def hook_emit_connection():
    """Yield one reused connection for batched ``emit_event(conn=...)`` flushes.

    The hook runner emits one telemetry row per chain module. A fresh
    connection per row makes the cold round-trip the dominant cost of a
    dispatch, and when that cost accrues against the runner's total deadline
    it can starve the guardrails at the tail of the chain. One shared
    connection collapses N cold connects into one.

    Best-effort: yields ``None`` when the active authority cannot be opened,
    so callers transparently degrade to per-call connections. Targets the
    same authority ``emit_event`` resolves by default.
    """
    conn = None
    try:
        conn = connect()
    except Exception:  # noqa: BLE001 — best-effort; degrade to per-call conns
        conn = None
    try:
        yield conn
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 — close failures are non-fatal
                pass


def _configured_min_severity(
    conn: Any,
    event_name: str,
    source_type: str,
) -> str:
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    min_sev = query_scalar(
        conn,
        "SELECT min_severity FROM severity_config "
        f"WHERE event_name={p} AND source_type={p} LIMIT 1",
        (event_name, source_type),
    )
    if min_sev is None:
        min_sev = query_scalar(
            conn,
            "SELECT min_severity FROM severity_config "
            f"WHERE event_name={p} AND source_type='*' LIMIT 1",
            (event_name,),
        )
    if min_sev is None:
        min_sev = query_scalar(
            conn,
            "SELECT min_severity FROM severity_config "
            f"WHERE event_name='*' AND source_type={p} LIMIT 1",
            (source_type,),
        )
    if min_sev is None:
        min_sev = query_scalar(
            conn,
            "SELECT min_severity FROM severity_config "
            "WHERE event_name='*' AND source_type='*' LIMIT 1",
        )
    return min_sev or "INFO"


def check_severity_conn(
    conn: Any,
    event_name: str,
    source_type: str,
    sev: str,
) -> bool:
    """Return True if the event passes the write-side severity filter."""
    from yoke_core.domain.events_crud import severity_num

    savepoint = "_yoke_severity_check"
    use_savepoint = db_backend.connection_is_postgres(conn)
    try:
        if use_savepoint:
            conn.execute(f"SAVEPOINT {savepoint}")
        passes = severity_num(sev) >= severity_num(
            _configured_min_severity(conn, event_name, source_type)
        )
        if use_savepoint:
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        return passes
    except db_backend.operational_error_types(conn):
        if use_savepoint:
            try:
                conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            except Exception:
                pass
        return severity_num(sev) >= severity_num("INFO")


def check_severity(
    db_path: Optional[str],
    event_name: str,
    source_type: str,
    sev: str,
) -> bool:
    """Return True if the event passes the write-side severity filter."""
    conn = None
    try:
        conn = connect(db_path)
        return check_severity_conn(conn, event_name, source_type, sev)
    finally:
        if conn is not None:
            conn.close()


def cmd_insert(
    db_path: Optional[str] = None,
    *,
    event_id: str,
    source_type: str,
    session_id: str,
    event_kind: str,
    event_type: str,
    event_name: str,
    severity: str = "INFO",
    event_outcome: Optional[str] = None,
    org_id: Optional[str] = None,
    actor_id: Optional[int] = None,
    environment: Optional[str] = None,
    service: str = "cli",
    project: str = "yoke",
    item_id: Optional[str] = None,
    task_num: Optional[int] = None,
    agent: Optional[str] = None,
    tool_name: Optional[str] = None,
    duration_ms: Optional[int] = None,
    exit_code: Optional[int] = None,
    trace_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    anomaly_flags: Optional[str] = None,
    tool_use_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    hook_event_name: Optional[str] = None,
    envelope: Optional[str] = None,
    created_at: Optional[str] = None,
    skip_severity: bool = False,
) -> bool:
    """Insert an event row. Deduplicates on event_id."""
    from yoke_core.domain.events_crud import (
        VALID_SOURCE_TYPES,
        normalize_event_item_id,
        normalize_severity,
    )

    raw_item_id = item_id
    if source_type not in VALID_SOURCE_TYPES:
        raise ValueError(
            f"source_type must be one of: {', '.join(VALID_SOURCE_TYPES)}"
        )
    severity = normalize_severity(severity)

    # Write-side severity filter
    if not skip_severity:
        if not check_severity(db_path, event_name, source_type, severity):
            return False  # silently dropped

    conn = connect(db_path)
    try:
        assert_event_name_not_retired(conn, event_name)
        # Unresolvable project tokens index the event as global (NULL
        # project): a universe without the named project row must still
        # accept every event write. Local import avoids a module cycle.
        from yoke_core.domain.events_project_identity import (
            resolve_project_id_for_event,
        )

        project_id = resolve_project_id_for_event(conn, db_path, project)
        if raw_item_id is None:
            item_id = None
        else:
            try:
                item_id = str(parse_item_id(raw_item_id, project=project, conn=conn))
            except ValueError:
                item_id = normalize_event_item_id(raw_item_id)
        conn.execute(
            """INSERT INTO events (
                event_id, source_type, session_id, severity,
                event_kind, event_type, event_name, event_outcome,
                org_id, actor_id, environment, service, project_id,
                item_id, task_num, agent, tool_name,
                duration_ms, exit_code, trace_id, parent_id,
                anomaly_flags, tool_use_id, turn_id,
                hook_event_name, envelope, created_at
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s
            )
            ON CONFLICT(event_id) DO NOTHING""",
            (
                event_id, source_type, session_id, severity,
                event_kind, event_type, event_name, event_outcome,
                org_id, actor_id, environment, service, project_id,
                item_id, task_num, agent, tool_name,
                duration_ms, exit_code, trace_id, parent_id,
                anomaly_flags, tool_use_id, turn_id,
                hook_event_name, envelope, created_at or iso8601_now(),
            ),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def cmd_severity_config_set(
    db_path: Optional[str] = None,
    event_name: str = "*",
    source_type: str = "*",
    min_severity: str = "INFO",
) -> str:
    """Set a severity config entry."""
    from yoke_core.domain.events_crud import VALID_SEVERITIES

    if min_severity not in VALID_SEVERITIES:
        raise ValueError(
            f"min_severity must be one of: {', '.join(VALID_SEVERITIES)}"
        )
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT INTO severity_config (event_name, source_type, min_severity, created_at) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT(event_name, source_type) "
            "DO UPDATE SET min_severity=%s",
            (event_name, source_type, min_severity, iso8601_now(), min_severity),
        )
        conn.commit()
        return (
            f"Set severity config: event_name='{event_name}' "
            f"source_type='{source_type}' min_severity={min_severity}"
        )
    finally:
        conn.close()


def cmd_severity_config_list(db_path: Optional[str] = None) -> str:
    """List all severity config entries."""
    from yoke_core.domain.events_crud import _format_rows

    conn = connect(db_path)
    try:
        rows = query_rows(
            conn,
            "SELECT id, event_name, source_type, min_severity, created_at "
            "FROM severity_config ORDER BY event_name ASC, source_type ASC",
        )
        return _format_rows(rows)
    finally:
        conn.close()


def cmd_severity_check(
    db_path: Optional[str] = None,
    event_name: str = "",
    source_type: str = "",
    sev: str = "INFO",
) -> str:
    """Return 'PASS' or 'DROP'."""
    if check_severity(db_path, event_name, source_type, sev):
        return "PASS"
    return "DROP"
