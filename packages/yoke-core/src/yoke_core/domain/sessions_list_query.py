"""SQL for the sessions roster read.

The shared row shape + joins and the two query shapes
:func:`yoke_core.domain.sessions_list_read.list_sessions` runs: the flat
newest-N read and the per-project-windowed roster (each project — and the
NULL-project partition — gets its own newest-N slice).
"""

from __future__ import annotations

#: The activity stamp every read orders by: the later of the two timestamps as
#: uniform ISO-8601 text (lexicographic order matches chronological order).
_ACTIVITY = "GREATEST(COALESCE(s.last_tool_call_at, ''), s.last_heartbeat)"

#: Row shape shared by both query shapes.
_SELECT = (
    "SELECT s.session_id, s.executor, s.executor_display_name, s.model, "
    "s.execution_lane, "
    "s.mode, s.workspace, s.project_id, pr.slug AS project, "
    "s.offered_at, s.last_heartbeat, s.last_tool_call_at, "
    "s.ended_at, s.current_item_id, s.actor_id, "
    "a.kind AS actor_kind, i.title AS current_item_title, "
    "i.workflow_id AS current_item_workflow_id, "
    "i.workflow_version_id AS current_item_workflow_version_id"
)
_JOINS = (
    "FROM harness_sessions s "
    "LEFT JOIN projects pr ON pr.id = s.project_id "
    "LEFT JOIN actors a ON a.id = s.actor_id "
    "LEFT JOIN items i ON CAST(i.id AS TEXT) = CAST(s.current_item_id AS TEXT)"
)


def build_sessions_query(where: str, *, windowed: bool) -> str:
    """The roster SQL. ``windowed`` gives each project its own newest-N slice
    (a ``%s`` per-project cap bind before the overall ``LIMIT %s``); otherwise
    it is the flat newest-N read (a single trailing ``LIMIT %s``)."""
    if windowed:
        return (
            f"SELECT * FROM ({_SELECT}, "
            f"ROW_NUMBER() OVER (PARTITION BY s.project_id "
            f"ORDER BY {_ACTIVITY} DESC) AS _rn "
            f"{_JOINS} {where}) ranked "
            "WHERE _rn <= %s "
            "ORDER BY GREATEST(COALESCE(last_tool_call_at, ''), "
            "last_heartbeat) DESC LIMIT %s"
        )
    return f"{_SELECT} {_JOINS} {where} ORDER BY {_ACTIVITY} DESC LIMIT %s"


__all__ = ["build_sessions_query"]
