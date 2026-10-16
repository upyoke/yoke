"""Dashboard collection and pure rendering of named widget data."""

from typing import List, Optional
from yoke_contracts.board.sections import task_expanded_count
from yoke_contracts.board.widgets_activity import (
    collect_weather_count,
    collect_activity_series,
)
from yoke_contracts.board.widgets_badges import (
    collect_age_counts,
    collect_workflow_counts,
    collect_achievement_counts,
)
from yoke_contracts.board.widgets_velocity_meter import collect_velocity_series
from yoke_contracts.board.widget_data import (
    render_weather_count,
    render_activity_series,
    render_age_counts,
    render_workflow_counts,
    render_achievement_counts,
    render_velocity_series,
)


def collect_dashboard_data(db, config, scope, tex_done, repo_root=None) -> dict:
    """Read only enabled widgets, with named values rather than a query plan."""
    data = {}
    if config.dashboard_weather:
        data["weather"] = collect_weather_count(db, config, scope)
    if config.dashboard_velocity:
        data["activity"] = collect_activity_series(db, config, scope, repo_root)
    if config.dashboard_badges:
        data["achievements"] = collect_achievement_counts(db, config, scope, tex_done)
    if config.dashboard_velocity_meter:
        data["velocity"] = collect_velocity_series(db, config, scope, repo_root)
    if config.dashboard_age:
        data["age"] = collect_age_counts(db, config, scope)
    if config.dashboard_workflows:
        data["workflows"] = collect_workflow_counts(db, config, scope)
    return data


def render_dashboard_data(data: dict) -> List[str]:
    """Lay out enabled widgets from one collected snapshot."""
    lines = []
    if "weather" in data:
        lines.extend(["", render_weather_count(data["weather"])])
    activity = (
        render_activity_series(
            *(
                data["activity"][key]
                for key in (
                    "dates",
                    "day_counts",
                    "streak",
                    "active_days",
                    "project_days",
                )
            )
        )
        if "activity" in data
        else None
    )
    badges = (
        render_achievement_counts(
            *(
                data["achievements"][key]
                for key in ("done", "streak", "bug_count", "idea_count")
            )
        )
        if "achievements" in data
        else None
    )
    row = _combine_row(activity, badges)
    if row:
        lines.extend(["", row])
    if "velocity" in data:
        lines.append("")
        lines.extend(
            render_velocity_series(
                *(
                    data["velocity"][key]
                    for key in ("dates", "activity", "code", "issues", "strategy")
                )
            )
        )
    age = render_age_counts(data["age"]) if data.get("age") is not None else None
    workflows = (
        render_workflow_counts(data["workflows"]) if "workflows" in data else None
    )
    row = _combine_row(age, workflows)
    if row:
        lines.extend(["", row])
    return lines


def render_dashboard(
    db, config, scope, buckets, epic_task_counts, repo_root
) -> List[str]:
    """Compose the same collector and renderer for an in-process caller."""
    done = task_expanded_count(buckets.get("done", []), epic_task_counts)
    return render_dashboard_data(
        collect_dashboard_data(db, config, scope, done, repo_root)
    )


def _combine_row(left: Optional[str], right: Optional[str]) -> Optional[str]:
    """Combine two widget outputs with `` | `` separator.

    Returns ``None`` if both are empty/None.
    """
    if left and right:
        return f"{left} | {right}"
    return left or right


__all__ = ["collect_dashboard_data", "render_dashboard_data", "render_dashboard"]
