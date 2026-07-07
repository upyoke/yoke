"""Leaf constants + row formatting for events read surfaces.

Import-order leaf: ``events_crud`` re-exports everything here for its
existing consumers, while the read modules (``events_queries``,
``events_audit_presets``, ``events_reporting``) import from THIS module
so they no longer participate in ``events_crud``'s tail-import cycle
(importing ``events_queries`` before ``events_crud`` used to raise
ImportError on the partially-initialised parent).
"""

from __future__ import annotations

from typing import Any, Dict, List

VALID_SEVERITIES = ("DEBUG", "INFO", "STATUS", "WARN", "ERROR", "FATAL")
SEVERITY_ORDER: Dict[str, int] = {
    "DEBUG": 0,
    "INFO": 1,
    "STATUS": 2,
    "WARN": 3,
    "ERROR": 4,
    "FATAL": 5,
}

# Standard SELECT columns (matches shell's _EVT_SELECT_COLS)
_EVT_SELECT_COLS = (
    "id, event_id, source_type, session_id, severity, event_kind, event_type, "
    "event_name, event_outcome, COALESCE(user_id,''), COALESCE(org_id,''), "
    "COALESCE(CAST(actor_id AS TEXT),''), COALESCE(environment,''), service, "
    "COALESCE((SELECT p.slug FROM projects p WHERE p.id = events.project_id), ''), "
    "COALESCE(item_id,''), COALESCE(CAST(task_num AS TEXT),''), COALESCE(agent,''), "
    "COALESCE(tool_name,''), COALESCE(CAST(duration_ms AS TEXT),''), COALESCE(CAST(exit_code AS TEXT),''), "
    "COALESCE(trace_id,''), COALESCE(parent_id,''), COALESCE(anomaly_flags,''), "
    "created_at"
)

# Result names for `_EVT_SELECT_COLS`, in SELECT order. Keep the two
# tuples in lockstep — the typed events.* read handlers zip them.
EVT_COLUMN_NAMES = (
    "id", "event_id", "source_type", "session_id", "severity",
    "event_kind", "event_type", "event_name", "event_outcome", "user_id",
    "org_id", "actor_id", "environment", "service", "project", "item_id",
    "task_num", "agent", "tool_name", "duration_ms", "exit_code",
    "trace_id", "parent_id", "anomaly_flags", "created_at",
)

# Registry SELECT columns
_REG_SELECT_COLS = (
    "event_name, event_kind, event_type, owner_service, "
    "description, COALESCE(context_schema,''), severity_default, "
    "COALESCE(added_in,''), status"
)


def severity_num(sev: str) -> int:
    """Return numeric severity level (0=DEBUG .. 5=FATAL), defaulting to 1 (INFO)."""
    return SEVERITY_ORDER.get(sev, 1)


def _format_rows(rows: List[Any]) -> str:
    """Format sqlite3.Row list as pipe-delimited lines (matching shell output).

    NULL values are rendered as empty strings to match sqlite3 CLI behavior.
    """
    lines = []
    for row in rows:
        lines.append("|".join("" if v is None else str(v) for v in tuple(row)))
    return "\n".join(lines)
