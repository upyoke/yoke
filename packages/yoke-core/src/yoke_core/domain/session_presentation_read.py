"""Definition-owned presentation for session read models."""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.executor_labels import executor_presentation
from yoke_contracts.project_contract.project_keys import (
    SESSION_ROUTING_CAPABILITY,
)
from yoke_contracts.session_lane import lane_presentation


def _lane_display(conn: Any, project_id: Any, lane: Any) -> dict[str, str]:
    settings: dict[str, Any] = {}
    if project_id is not None:
        row = conn.execute(
            "SELECT settings FROM project_capabilities WHERE project_id=%s AND type=%s",
            (int(project_id), SESSION_ROUTING_CAPABILITY),
        ).fetchone()
        if row is not None:
            raw = row[0]
            try:
                parsed = raw if isinstance(raw, dict) else json.loads(str(raw or "{}"))
            except (TypeError, ValueError):
                parsed = {}
            if isinstance(parsed, dict):
                settings = parsed
    return lane_presentation(str(lane or ""), settings)


def session_presentation(conn: Any, row: dict[str, Any]) -> dict[str, Any]:
    """Return execution and observed-presentation metadata for a session."""
    display_name = str(row.get("executor_surface") or row.get("executor") or "")
    executor = executor_presentation(display_name)
    lane = _lane_display(conn, row.get("project_id"), row.get("execution_lane"))
    return {
        "lane_label": lane["label"],
        "lane_glyph": lane["glyph"],
        "executor_mark": executor["mark"],
        "executor_class_name": executor["class_name"],
        "presentation_surface": row.get("presentation_surface"),
        "presentation_state": row.get("presentation_state"),
        "presentation_mode": row.get("presentation_mode"),
        "presentation_source": row.get("presentation_source"),
        "presentation_observed_at": row.get("presentation_observed_at"),
    }


__all__ = ["session_presentation"]
