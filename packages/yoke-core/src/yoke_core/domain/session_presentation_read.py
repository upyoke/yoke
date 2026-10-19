"""Definition-owned presentation for session read models."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from yoke_contracts.executor_labels import executor_presentation
from yoke_contracts.levels import (
    Level,
    LevelsError,
    level_for_session,
    level_presentation,
    level_reason,
    resolve_effective_levels,
)
from yoke_contracts.session_level import UNRESOLVED_EXECUTION_LEVEL
from yoke_contracts.model_level_resolution import (
    routing_effort_of,
    routing_model_of,
)
from yoke_core.domain.universe_levels import (
    UniverseLevelsError,
    project_routing_settings,
    stored_universe_levels,
)


def levels_by_project(
    conn: Any,
    project_ids: Iterable[Any],
) -> dict[Optional[int], tuple[Level, ...]]:
    """The levels each named project reads, resolved once per project.

    A roster page holds many sessions per project, and every row's level
    glyph comes from its project's effective levels. Resolving the distinct
    projects once here keeps the read's cost proportional to the projects on
    the page rather than to its rows. An unreadable stored document labels
    nothing; ``yoke projects level-summary get`` names its repair.
    """
    distinct = [int(value) for value in dict.fromkeys(project_ids) if value is not None]
    try:
        universe = stored_universe_levels(conn)
    except UniverseLevelsError:
        universe = None
    resolved: dict[Optional[int], tuple[Level, ...]] = {}
    for project_id in [None, *distinct]:
        try:
            resolved[project_id] = resolve_effective_levels(
                project_routing_settings(conn, project_id), universe
            )[0]
        except (LevelsError, UniverseLevelsError):
            resolved[project_id] = ()
    return resolved


def session_presentation(
    row: Mapping[str, Any],
    *,
    levels: Mapping[Optional[int], tuple[Level, ...]],
    records=(),
) -> dict[str, Any]:
    """Return execution and observed-presentation metadata for a session.

    *levels* is the already-resolved :func:`levels_by_project` map.
    """
    display_name = str(row.get("executor_surface") or row.get("executor") or "")
    executor = executor_presentation(display_name)
    project_id = row.get("project_id")
    key = int(project_id) if project_id is not None else None
    effective = levels.get(key, levels.get(None, ()))
    model = routing_model_of(row.get("model"), row.get("requested_model"))
    effort = routing_effort_of(
        row.get("reasoning_effort"),
        row.get("requested_reasoning_effort"),
        row.get("model"),
    )
    execution_level = (
        level_for_session(
            effective,
            executor=display_name,
            model=model,
            reasoning_effort=effort,
            records=records,
        )
        or UNRESOLVED_EXECUTION_LEVEL
    )
    reason = level_reason(effective, model=model, effort=effort, records=records)
    level = level_presentation(effective, execution_level, reason=reason)
    return {
        "execution_level": execution_level,
        "level_label": level["label"],
        "level_glyph": level["glyph"],
        "level_reason": level.get("reason") or None,
        "executor_mark": executor["mark"],
        "executor_class_name": executor["class_name"],
        "presentation_surface": row.get("presentation_surface"),
        "presentation_state": row.get("presentation_state"),
        "presentation_mode": row.get("presentation_mode"),
        "presentation_source": row.get("presentation_source"),
        "presentation_observed_at": row.get("presentation_observed_at"),
    }


__all__ = ["levels_by_project", "session_presentation"]
