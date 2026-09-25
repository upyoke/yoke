"""SQL for the sessions roster read.

The shared row shape + joins and the two query shapes
:func:`yoke_core.domain.sessions_list_read.list_sessions` runs: the flat
newest-N read and the per-project-windowed roster (each project — and the
NULL-project partition — gets its own newest-N slice, and every session
holding a live item work claim rides along whatever its rank).
"""

from __future__ import annotations

#: The activity stamp every read orders by: the later of the two timestamps as
#: uniform ISO-8601 text (lexicographic order matches chronological order).
_ACTIVITY = "GREATEST(COALESCE(s.last_tool_call_at, ''), s.last_heartbeat)"

#: Whether the session holds a live item work claim. The windowed roster keeps
#: these rows past its per-project cap: a holder parked at its item's release
#: wait is idle by design, and ranking it by activity alone would drop the
#: holder a claimed card has to name.
_HOLDS_ITEM = (
    "EXISTS (SELECT 1 FROM work_claims wc "
    "WHERE wc.session_id = s.session_id "
    "AND wc.target_kind = 'item' AND wc.released_at IS NULL)"
)

#: Row shape shared by both query shapes.
_SELECT = (
    "SELECT s.session_id, s.executor, s.executor_surface, s.model, "
    "s.reasoning_effort, s.context_window_tokens, s.requested_model, "
    "s.usage_totals, "
    "s.presentation_surface, s.presentation_state, s.presentation_mode, "
    "s.presentation_source, s.presentation_observed_at, "
    "s.execution_lane, "
    "s.mode, s.quiet_reason, s.keepalive_until, s.keepalive_reason, "
    "s.workspace, s.project_id, pr.slug AS project, "
    "s.offered_at, s.last_heartbeat, s.last_tool_call_at, "
    "s.episode_started_at, s.turn_posture, s.turn_posture_at, "
    "s.native_process_gone_at, s.native_process_gone_evidence, "
    "s.ended_at, s.terminated_at, s.terminated_by_actor_id, "
    "s.terminated_by_session_id, s.termination_reason, s.current_item_id, s.actor_id, "
    "a.kind AS actor_kind, i.title AS current_item_title, "
    "i.status AS current_item_status, "
    "i.project_id AS current_item_project_id, "
    "i.project_sequence AS current_item_project_sequence, "
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
    (a ``%s`` per-project cap bind before the overall ``LIMIT %s``) plus every
    item-claim holder, which also sorts ahead of the overall limit; otherwise
    it is the flat newest-N read (a single trailing ``LIMIT %s``)."""
    if windowed:
        return (
            f"SELECT * FROM ({_SELECT}, {_HOLDS_ITEM} AS _holds_item, "
            f"ROW_NUMBER() OVER (PARTITION BY s.project_id "
            f"ORDER BY {_ACTIVITY} DESC) AS _rn "
            f"{_JOINS} {where}) ranked "
            "WHERE _rn <= %s OR _holds_item "
            "ORDER BY _holds_item DESC, "
            "GREATEST(COALESCE(last_tool_call_at, ''), "
            "last_heartbeat) DESC LIMIT %s"
        )
    return f"{_SELECT} {_JOINS} {where} ORDER BY {_ACTIVITY} DESC LIMIT %s"


__all__ = ["build_sessions_query"]
