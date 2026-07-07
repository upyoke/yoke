"""Dashboard widget-row assembly for the board renderer.

Extracted from :mod:`yoke_core.board.renderer` to keep that module
under the authored-line cap. ``db`` is any handle honoring the BoardDBLike
seam (live, recording, or replay).
"""

from __future__ import annotations

from typing import Dict, List, Optional

from yoke_contracts.board.config import BoardConfig
from yoke_contracts.board.sections import task_expanded_count
from yoke_contracts.board.widgets import (
    render_achievement_badges,
    render_age_heatmap,
    render_type_badges,
    render_velocity_meter,
    render_velocity_sparkline,
    render_weather,
)


def render_dashboard(
    db,
    config: BoardConfig,
    scope: str,
    buckets: Dict[str, list],
    epic_task_counts: Dict[int, int],
    repo_root: Optional[str],
) -> List[str]:
    """Render dashboard widget rows in canonical order.

    Canonical order:
    1. Weather (if enabled)
    2. Row 1: velocity sparkline | achievement badges
    3. Velocity meter (if enabled)
    4. Row 2: age heatmap | type badges
    """
    lines: List[str] = []

    # Weather
    if config.dashboard_weather:
        weather = render_weather(db, config, scope)
        if weather:
            lines.append("")
            lines.append(weather)

    # Row 1: velocity sparkline | achievement badges
    velocity = None
    if config.dashboard_velocity:
        velocity = render_velocity_sparkline(db, config, scope, repo_root)

    # Compute tex_done for badge thresholds
    done_items = buckets.get("done", [])
    tex_done = task_expanded_count(done_items, epic_task_counts)

    badges = None
    if config.dashboard_badges:
        badges = render_achievement_badges(db, config, scope, tex_done)

    row1 = _combine_row(velocity, badges)
    if row1:
        lines.append("")
        lines.append(row1)

    # Velocity meter (4 rows, if enabled)
    if config.dashboard_velocity_meter:
        meter_lines = render_velocity_meter(db, config, scope, repo_root)
        if meter_lines:
            lines.append("")
            lines.extend(meter_lines)

    # Row 2: age heatmap | type badges
    age = None
    if config.dashboard_age:
        age = render_age_heatmap(db, config, scope)

    types = None
    if config.dashboard_types:
        types = render_type_badges(db, config, scope)

    row2 = _combine_row(age, types)
    if row2:
        lines.append("")
        lines.append(row2)

    return lines


def _combine_row(left: Optional[str], right: Optional[str]) -> Optional[str]:
    """Combine two widget outputs with `` | `` separator.

    Returns ``None`` if both are empty/None.
    """
    if left and right:
        return f"{left} | {right}"
    return left or right


__all__ = ["render_dashboard"]
