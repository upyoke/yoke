"""Where a launch could land, and how much is already running there.

The standing picture rather than a failure: no row here is an alarm. It is
kept apart from the detectors because it answers the question that follows
every staffing decision -- once the seat knows what needs a worker, this is
what says whether a worker can be started and where the load already sits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_contracts.executor_labels import KNOWN_SURFACE_LABELS
from yoke_contracts.session_control.capabilities import capability_for_surface
from yoke_contracts.session_control.launch_origin import LAUNCH_ORIGINS
from yoke_core.domain.session_launch_eligibility import derive_launch_eligibility
from yoke_core.domain.steering_fleet_report_detectors import marker


@dataclass(frozen=True)
class SurfaceReadiness:
    """One ``(machine, surface)`` pair a launch could reach right now."""

    machine_id: str
    surface: str


def launchable_surfaces(
    conn: Any,
    *,
    project_id: int,
    now: str,
) -> tuple[SurfaceReadiness, ...]:
    """Every ``(machine, surface)`` a launch could reach for this project.

    Read through the same eligibility composition the launch preview uses, so
    the report can never claim a surface the launch plane would refuse.
    """
    ready: set[tuple[str, str]] = set()
    for surface in KNOWN_SURFACE_LABELS:
        capability = capability_for_surface(surface)
        if capability is None or capability.create == "none":
            continue
        snapshot = derive_launch_eligibility(
            conn,
            project_id=int(project_id),
            surface=surface,
            machine_id=None,
            now=now,
        )
        for relay in snapshot.relays:
            ready.add((relay.machine_id, surface))
    return tuple(
        SurfaceReadiness(machine_id=machine, surface=surface)
        for machine, surface in sorted(ready)
    )


def live_session_counts(
    conn: Any, *, project_id: int
) -> tuple[tuple[str, str, int], ...]:
    """Live sessions in this project, grouped by machine and surface."""
    p = marker(conn)
    rows = conn.execute(
        f"""SELECT machine_id, executor_surface, COUNT(*) AS n
              FROM harness_sessions
             WHERE ended_at IS NULL AND terminated_at IS NULL
               AND project_id = {p}
               AND COALESCE(machine_id, '') <> ''
               AND COALESCE(executor_surface, '') <> ''
             GROUP BY machine_id, executor_surface""",
        (int(project_id),),
    ).fetchall()
    return tuple(
        (str(row["machine_id"]), str(row["executor_surface"]), int(row["n"]))
        for row in rows
    )


def live_launch_origin_counts(
    conn: Any, *, project_id: int
) -> tuple[tuple[str, int], ...]:
    """Live sessions joined to their launch origin, including zero counts.

    Sessions with no matching ``session_launches.registered_session_id`` are
    omitted from the split. Both vocabulary values are always present.
    """
    p = marker(conn)
    rows = conn.execute(
        f"""SELECT l.origin AS origin, COUNT(*) AS n
              FROM harness_sessions s
              JOIN session_launches l ON l.registered_session_id = s.session_id
             WHERE s.ended_at IS NULL AND s.terminated_at IS NULL
               AND s.project_id = {p}
             GROUP BY l.origin""",
        (int(project_id),),
    ).fetchall()
    counted = {str(row["origin"]): int(row["n"]) for row in rows}
    return tuple((origin, counted.get(origin, 0)) for origin in LAUNCH_ORIGINS)


__all__ = [
    "SurfaceReadiness",
    "launchable_surfaces",
    "live_launch_origin_counts",
    "live_session_counts",
]
