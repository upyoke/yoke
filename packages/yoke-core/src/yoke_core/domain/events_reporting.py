"""Registry CRUD writes for the Yoke event platform.

Owns the seven small CRUD functions for the ``event_registry`` table:
``cmd_registry_add``, ``cmd_registry_get``, ``cmd_registry_list``,
``cmd_registry_update``, ``cmd_registry_deprecate``,
``cmd_registry_delete``, and ``cmd_registry_count``.

Discovery primitives (AST/regex helpers + ``cmd_registry_discover``) live
in ``events_registry_discovery``. Reporting queries
(``cmd_registry_audit``, ``cmd_registry_diff``) live in
``events_registry_audit``. This module re-exports those names so the
public surface — what ``events_crud`` re-exports and what historical
callers import directly from ``events_reporting`` — remains identical.

Imports of constants/helpers from ``events_crud`` happen lazily inside
each function. ``events_crud`` does a late re-export from this module
after defining its own helpers; binding ``events_crud`` symbols at
module top-level here would re-enter the partially-initialised
``events_crud`` whenever a caller imports ``events_reporting`` directly,
which raises ``ImportError`` for the late-bound names. Function-local
imports break that cycle while preserving ``events_crud``'s late
re-export.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.db_helpers import connect, query_one, query_rows, query_scalar

# Re-exports: discovery primitives + cmd_registry_discover.
from yoke_core.domain.events_registry_discovery import (
    _discover_python_event_names,
    _extract_event_name_from_line,
    _join_continuation_lines,
    _py_call_name,
    _py_string_value,
    _validate_event_name,
    cmd_registry_discover,
)

# Re-exports: registry audit + diff.
from yoke_core.domain.events_registry_audit import (
    cmd_registry_audit,
    cmd_registry_diff,
)

__all__ = [
    "_discover_python_event_names",
    "_extract_event_name_from_line",
    "_join_continuation_lines",
    "_py_call_name",
    "_py_string_value",
    "_validate_event_name",
    "cmd_registry_add",
    "cmd_registry_audit",
    "cmd_registry_count",
    "cmd_registry_delete",
    "cmd_registry_deprecate",
    "cmd_registry_diff",
    "cmd_registry_discover",
    "cmd_registry_get",
    "cmd_registry_list",
    "cmd_registry_update",
]


def cmd_registry_add(
    db_path: Optional[str] = None,
    *,
    name: str,
    kind: str,
    event_type: str,
    service: str,
    description: str,
    context_schema: Optional[str] = None,
    severity: str = "INFO",
    added_in: Optional[str] = None,
) -> None:
    """Add a registry entry if it is not already present."""
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT INTO event_registry ("
            "  event_name, event_kind, event_type, owner_service,"
            "  description, context_schema, severity_default, added_in, status"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'active') "
            "ON CONFLICT(event_name) DO NOTHING",
            (name, kind, event_type, service, description, context_schema, severity, added_in),
        )
        conn.commit()
    finally:
        conn.close()


def cmd_registry_get(db_path: Optional[str] = None, name: str = "") -> str:
    """Get a registry entry. Returns pipe-delimited string or raises."""
    from yoke_core.domain.events_select import _REG_SELECT_COLS

    conn = connect(db_path)
    try:
        row = query_one(
            conn,
            f"SELECT {_REG_SELECT_COLS} FROM event_registry WHERE event_name=%s",
            (name,),
        )
        if row is None:
            raise LookupError(f"event '{name}' not found in registry")
        return "|".join(str(v) for v in tuple(row))
    finally:
        conn.close()


def cmd_registry_list(
    db_path: Optional[str] = None,
    status: str = "active",
    kind: Optional[str] = None,
    service: Optional[str] = None,
) -> str:
    """List registry entries with optional filters."""
    from yoke_core.domain.events_select import _REG_SELECT_COLS, _format_rows

    parts: list[str] = []
    params: list[Any] = []

    if status != "all":
        parts.append("status=%s")
        params.append(status)
    if kind:
        parts.append("event_kind=%s")
        params.append(kind)
    if service:
        parts.append("owner_service=%s")
        params.append(service)

    where = ("WHERE " + " AND ".join(parts)) if parts else ""
    conn = connect(db_path)
    try:
        rows = query_rows(
            conn,
            f"SELECT {_REG_SELECT_COLS} FROM event_registry {where} "
            "ORDER BY event_name ASC",
            tuple(params),
        )
        return _format_rows(rows)
    finally:
        conn.close()


def cmd_registry_update(
    db_path: Optional[str] = None,
    name: str = "",
    **kwargs: str,
) -> None:
    """Update registry entry fields."""
    conn = connect(db_path)
    try:
        exists = query_scalar(
            conn, "SELECT COUNT(*) FROM event_registry WHERE event_name=%s", (name,)
        )
        if exists == 0:
            raise LookupError(f"event '{name}' not found in registry")

        field_map = {
            "description": "description",
            "context_schema": "context_schema",
            "event_kind": "event_kind",
            "event_type": "event_type",
            "severity": "severity_default",
            "status": "status",
        }
        set_parts: list[str] = []
        params: list[Any] = []
        for key, val in kwargs.items():
            if key in field_map and val is not None:
                set_parts.append(f"{field_map[key]}=%s")
                params.append(val)

        if not set_parts:
            raise ValueError("no fields to update")

        params.append(name)
        conn.execute(
            f"UPDATE event_registry SET {', '.join(set_parts)} WHERE event_name=%s",
            tuple(params),
        )
        conn.commit()
    finally:
        conn.close()


def cmd_registry_deprecate(db_path: Optional[str] = None, name: str = "") -> None:
    """Set registry entry status to deprecated."""
    conn = connect(db_path)
    try:
        exists = query_scalar(
            conn, "SELECT COUNT(*) FROM event_registry WHERE event_name=%s", (name,)
        )
        if exists == 0:
            raise LookupError(f"event '{name}' not found in registry")
        conn.execute(
            "UPDATE event_registry SET status='deprecated' WHERE event_name=%s",
            (name,),
        )
        conn.commit()
    finally:
        conn.close()


def cmd_registry_delete(db_path: Optional[str] = None, name: str = "") -> None:
    """Delete a registry entry."""
    conn = connect(db_path)
    try:
        exists = query_scalar(
            conn, "SELECT COUNT(*) FROM event_registry WHERE event_name=%s", (name,)
        )
        if exists == 0:
            raise LookupError(f"event '{name}' not found in registry")
        conn.execute("DELETE FROM event_registry WHERE event_name=%s", (name,))
        conn.commit()
    finally:
        conn.close()


def cmd_registry_count(db_path: Optional[str] = None, status: Optional[str] = None) -> int:
    """Count registry entries, optionally filtered by status."""
    conn = connect(db_path)
    try:
        if not status or status == "all":
            return query_scalar(conn, "SELECT COUNT(*) FROM event_registry")
        return query_scalar(
            conn,
            "SELECT COUNT(*) FROM event_registry WHERE status=%s",
            (status,),
        )
    finally:
        conn.close()
