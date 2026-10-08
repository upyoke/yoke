"""Load the universe's launch capacity per level, and its project overrides.

Capacity is the union of what every live project can reach: the machines a
launch could land on per surface (the same eligibility the launch plane
derives), the quota meters those machines publish, and the live workers per
surface. :mod:`yoke_core.domain.universe_level_capacity` turns that into each
level's launch standing, and :mod:`yoke_core.domain.universe_level_next_launch`
previews, per project, where the caller's next launch at each level goes.
Projects whose ``session-routing`` capability carries a levels override are
listed with what their override changes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from yoke_contracts.levels import Level
from yoke_contracts.model_reference import lookup_model_reference
from yoke_contracts.model_reference_records import ModelReferenceError
from yoke_contracts.session_control.plan_limits import CLI_PLAN_LIMIT_SURFACES
from yoke_core.domain.model_reference_store import revision_at
from yoke_core.domain.steering_fleet_plan_capacity import compute_plan_limit
from yoke_core.domain.steering_fleet_report_capacity import (
    launchable_surfaces,
    live_session_counts,
)
from yoke_core.domain.steering_fleet_report_limits import load_plan_limits
from yoke_core.domain.universe_level_capacity import Meter, evaluate_level_capacity
from yoke_core.domain.universe_level_next_launch import Authorize, next_launches
from yoke_core.domain.universe_levels import effective_levels


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _projects(conn: Any) -> list[tuple[int, str, str]]:
    rows = conn.execute(
        "SELECT id, slug, name FROM projects WHERE retired_at IS NULL ORDER BY id"
    ).fetchall()
    return [(int(row[0]), str(row[1]), str(row[2] or row[1])) for row in rows]


def _display_names(conn: Any) -> Callable[[str], str]:
    """Name models from the published catalog; an unknown model shows its id."""
    try:
        records = revision_at(conn)["records"]
    except ModelReferenceError:
        records = ()

    def display(model: str) -> str:
        record = lookup_model_reference(model, records).record
        return (record.display_name if record else None) or model

    return display


def _override_changes(override: tuple[Level, ...], universe: tuple[Level, ...]):
    """Name what a project override changes against the universe levels."""
    base = {level.name: level for level in universe}
    names = {level.name for level in override}
    changes: list[list[str]] = []
    for level in override:
        if level.name not in base:
            changes.append([level.name, "added"])
            continue
        other = base[level.name]
        if level.options != other.options:
            changes.append([level.name, "options changed"])
        elif level.glyph != other.glyph:
            changes.append([level.name, "glyph changed"])
    changes.extend(
        [level.name, "removed"] for level in universe if level.name not in names
    )
    return changes


def read_level_capacity(conn: Any, *, authorize: Authorize) -> dict[str, Any]:
    """The Levels read: each level's launch standing, the next launch per
    project as ``authorize``'s caller would place it, and the overrides."""
    now = _now()
    universe, source = effective_levels(conn, None)
    projects = _projects(conn)
    meters: dict[tuple, Meter] = {}
    offered: set[tuple[str, str]] = set()
    live_workers = {surface: 0 for surface in CLI_PLAN_LIMIT_SURFACES}
    overrides: list[dict[str, Any]] = []
    for project_id, slug, name in projects:
        for ready in launchable_surfaces(conn, project_id=project_id, now=now):
            offered.add((ready.machine_id, ready.surface))
        for row in load_plan_limits(conn, project_id=project_id, now=now):
            computed = compute_plan_limit(row, now=now)
            key = (row.machine_id, row.surface, row.window_kind, row.scope, row.meter)
            meters[key] = Meter(
                machine_id=row.machine_id,
                surface=row.surface,
                window_kind=row.window_kind,
                scope=row.scope,
                status=row.status,
                remaining_percent=row.remaining_percent,
                headroom_percent=computed.headroom_percent,
            )
        for count in live_session_counts(conn, project_id=project_id):
            if count.surface in live_workers:
                live_workers[count.surface] += count.count
        levels, levels_source = effective_levels(conn, project_id)
        # "project" is the levels source an override reports, not a project name.
        overridden = levels_source == "project"
        overrides.append(
            {
                "project": slug,
                "name": name,
                "override": overridden,
                "changes": _override_changes(levels, universe) if overridden else [],
            }
        )
    display = _display_names(conn)
    levels = evaluate_level_capacity(
        universe,
        meters=tuple(meters.values()),
        offered=tuple(offered),
        display=display,
    )
    placed = next_launches(
        conn,
        universe,
        [(project_id, slug) for project_id, slug, _ in projects],
        authorize=authorize,
        display=display,
    )
    for level in levels:
        level["next_launches"] = placed[level["name"]]
    return {
        "read_at": now,
        "source": source,
        "usable_machines": len({machine for machine, _ in offered}),
        "live_workers": live_workers,
        "levels": levels,
        "projects": overrides,
    }


__all__ = ["read_level_capacity"]
