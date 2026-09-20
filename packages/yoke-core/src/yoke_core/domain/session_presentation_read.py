"""Definition-owned presentation for session read models."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from yoke_contracts.executor_labels import executor_presentation
from yoke_contracts.project_contract.project_keys import (
    SESSION_ROUTING_CAPABILITY,
)
from yoke_contracts.session_lane import lane_presentation
from yoke_core.domain import db_backend


def _parse_settings(raw: Any) -> dict[str, Any]:
    try:
        parsed = raw if isinstance(raw, dict) else json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def lane_settings_by_project(
    conn: Any,
    project_ids: Iterable[Any],
) -> dict[int, dict[str, Any]]:
    """Session-routing settings for the named projects, read in one query.

    A roster page holds many sessions per project, and the lane label of
    every one of them comes from that project's single routing capability
    row. Resolving the distinct projects once here is what keeps the read's
    cost proportional to the projects on the page rather than to its rows.
    """
    distinct = [
        int(value) for value in dict.fromkeys(project_ids) if value is not None
    ]
    if not distinct:
        return {}
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT project_id, settings FROM project_capabilities "
        f"WHERE type={marker} AND project_id IN ("
        + ",".join(marker for _ in distinct)
        + ")",
        (SESSION_ROUTING_CAPABILITY, *distinct),
    ).fetchall()
    return {
        int(dict(row)["project_id"]): _parse_settings(dict(row)["settings"])
        for row in rows
    }


def session_presentation(
    row: Mapping[str, Any],
    *,
    lane_settings: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    """Return execution and observed-presentation metadata for a session.

    *lane_settings* is the already-resolved
    :func:`lane_settings_by_project` map; a project absent from it simply
    has no routing capability, which renders the same as an empty one.
    """
    display_name = str(row.get("executor_surface") or row.get("executor") or "")
    executor = executor_presentation(display_name)
    project_id = row.get("project_id")
    settings = (
        lane_settings.get(int(project_id), {}) if project_id is not None else {}
    )
    lane = lane_presentation(str(row.get("execution_lane") or ""), dict(settings))
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


__all__ = ["lane_settings_by_project", "session_presentation"]
