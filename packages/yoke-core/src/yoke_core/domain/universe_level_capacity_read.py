"""Read the viewer's launch standing across projects they can operate.

Machine eligibility and access are shared with launches. Actionable surface
rejections appear once, outside the per-option quota and native-model blockers.
"""

from __future__ import annotations

from datetime import datetime
from yoke_contracts.timestamps import utc_now, format_instant
from typing import Any, Callable

from yoke_contracts.levels import Level
from yoke_contracts.model_reference import lookup_model_reference
from yoke_contracts.model_reference_records import ModelReferenceError
from yoke_contracts.session_control.extra_usage import EXTRA_BLOCKING_STATUSES
from yoke_contracts.session_control.model_billing_pools import extra_usage_status
from yoke_core.domain.plan_limit_extra_usage import extra_label_now
from yoke_contracts.session_control.plan_limits import CLI_PLAN_LIMIT_SURFACES
from yoke_core.domain.model_reference_store import revision_at
from yoke_core.domain.steering_fleet_plan_capacity import compute_plan_limit
from yoke_core.domain.steering_fleet_report_capacity import (
    surface_eligibility_snapshots,
    live_session_counts,
)
from yoke_core.domain.steering_fleet_report_limits import load_plan_limits
from yoke_core.domain.universe_level_capacity import Meter, evaluate_level_capacity
from yoke_core.domain.machine_launch_access import filter_by_machine_access
from yoke_core.domain.session_launch_types import (
    LaunchAuthorization,
    SessionLaunchError,
)

from yoke_core.domain.session_launch_machine_models import machine_native_models
from yoke_core.domain.session_model_catalog import current_model_records
from yoke_core.domain.quota_pool_order import read_pool_order
from yoke_core.domain.universe_levels import effective_levels


Authorize = Callable[[int], LaunchAuthorization]

UNAVAILABLE_REASONS = {
    "harness_signed_out": "signed out",
    "liveness_expired": "relay disconnected",
    "version_below_floor": "below version floor",
    "surface_disabled": "surface disabled",
    "machine_at_capacity": "at capacity",
}


def _now() -> datetime:
    return utc_now()


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
    """Each level's caller-accessible launch standing and project overrides."""
    now = _now()
    universe, source = effective_levels(conn, None)
    projects = _projects(conn)
    meters: dict[tuple, Meter] = {}
    offered: set[tuple[str, str]] = set()
    unavailable: dict[tuple[str, str], set[str]] = {}
    live_workers = {surface: 0 for surface in CLI_PLAN_LIMIT_SURFACES}
    overrides: list[dict[str, Any]] = []
    for project_id, slug, name in projects:
        try:
            auth = authorize(project_id)
        except SessionLaunchError:
            continue
        if not auth.can_operate_project:
            continue
        for surface, snapshot in surface_eligibility_snapshots(
            conn, project_id=project_id, now=now
        ):
            narrowed, denials = filter_by_machine_access(
                conn, snapshot, actor_id=auth.actor_id, project_id=project_id
            )
            offered.update((relay.machine_id, surface) for relay in narrowed.relays)
            names = {
                relay.machine_id: relay.hostname or relay.machine_id
                for relay in snapshot.relays
            }
            for machine in denials:
                unavailable.setdefault((machine, surface), set()).add(
                    f"{surface}: access denied on {names[machine]}"
                )
            for rejection in narrowed.machine_rejections:
                for code in rejection.codes:
                    if code in UNAVAILABLE_REASONS:
                        unavailable.setdefault(
                            (rejection.machine_id, surface), set()
                        ).add(
                            f"{surface}: {UNAVAILABLE_REASONS[code]} on {rejection.name}"
                        )
        for row in load_plan_limits(conn, project_id=project_id, now=now):
            computed = compute_plan_limit(row, now=now)
            extra = extra_usage_status(
                row.extra_usage, observed_at=row.observed_at, now=now
            )
            key = (row.machine_id, row.surface, row.window_kind, row.scope, row.meter)
            meters[key] = Meter(
                machine_id=row.machine_id,
                surface=row.surface,
                window_kind=row.window_kind,
                scope=row.scope,
                status=row.status,
                remaining_percent=row.remaining_percent,
                headroom_percent=computed.headroom_percent,
                extra_blocks=extra in EXTRA_BLOCKING_STATUSES,
                extra=extra_label_now(row, now=now),
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
        records=current_model_records(conn),
        native_models={
            machine: machine_native_models(conn, machine_id=machine)
            for machine in {machine for machine, _ in offered}
        },
    )
    return {
        "read_at": format_instant(now),
        "source": source,
        "unavailable": sorted(
            {
                line
                for pair, lines in unavailable.items()
                if pair not in offered
                for line in lines
            }
        ),
        "usable_machines": len({machine for machine, _ in offered}),
        "live_workers": live_workers,
        "levels": levels,
        "projects": overrides,
        "cursor_quota_order": list(read_pool_order(conn)),
    }


__all__ = ["read_level_capacity"]
