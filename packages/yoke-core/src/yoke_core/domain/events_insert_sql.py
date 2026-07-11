"""Event INSERT statement owned outside the emitter line budget."""

from __future__ import annotations


_INSERT_SQL = """
INSERT INTO events (
    event_id, event_name, event_kind, event_type, source_type,
    session_id, severity, event_outcome, org_id, environment,
    service, project_id,
    actor_id, item_id, task_num, agent, tool_name, duration_ms, exit_code,
    trace_id, parent_id, anomaly_flags, tool_use_id,
    turn_id, hook_event_name,
    envelope, created_at
) VALUES (
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s,
    %s, %s,
    %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s,
    %s, %s
)
ON CONFLICT(event_id) DO NOTHING
"""
