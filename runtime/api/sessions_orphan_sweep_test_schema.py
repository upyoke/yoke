"""Events table the orphaned-tool-call sweep tests read sentinels from."""

from __future__ import annotations

from runtime.api.sessions_api_stale_test_helpers import apply_ddl_statements


EVENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    event_id TEXT UNIQUE NOT NULL,
    source_type TEXT,
    session_id TEXT NOT NULL,
    severity TEXT,
    event_kind TEXT,
    event_type TEXT,
    event_name TEXT,
    event_outcome TEXT,
    service TEXT,
    project_id INTEGER DEFAULT 1 REFERENCES projects(id),
    item_id TEXT,
    task_num INTEGER,
    agent TEXT,
    tool_name TEXT,
    duration_ms INTEGER,
    exit_code INTEGER,
    anomaly_flags TEXT,
    tool_use_id TEXT,
    turn_id TEXT,
    hook_event_name TEXT,
    client_timing_id TEXT,
    envelope TEXT,
    created_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_tool_use_id_dedup
    ON events(tool_use_id, event_name) WHERE tool_use_id IS NOT NULL;
"""


def _seed_events(c) -> None:
    apply_ddl_statements(c, EVENTS_SCHEMA)
    c.commit()


__all__ = ["EVENTS_SCHEMA", "_seed_events"]
