"""Where a launch could land, and how much is already running there.

The standing picture rather than a failure: no row here is an alarm. It is
kept apart from the detectors because it answers the question that follows
every staffing decision -- once the seat knows what needs a worker, this is
what says whether a worker can be started and where the load already sits.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from yoke_contracts.executor_labels import KNOWN_SURFACE_LABELS
from yoke_contracts.session_control.capabilities import capability_for_surface
from yoke_contracts.session_control.launch_origin import LAUNCH_ORIGINS
from yoke_core.domain.session_launch_capacity import (
    MachineCapacity,
    machine_capacity,
)
from yoke_core.domain.session_launch_eligibility import derive_launch_eligibility
from yoke_core.domain.session_probe import not_probe_session_sql
from yoke_core.domain.steering_fleet_report_detectors import marker


MANUAL_SESSION_ORIGIN = "manual"


@dataclass(frozen=True)
class SurfaceReadiness:
    """One ``(machine, surface)`` pair a launch could reach right now."""

    machine_id: str
    surface: str


@dataclass(frozen=True)
class SessionCount:
    """Live sessions sharing one requested/served model selection."""

    machine_id: str
    surface: str
    count: int
    requested_model: str | None
    requested_reasoning_effort: str | None
    requested_context_window_tokens: int | None
    model: str | None
    reasoning_effort: str | None
    context_window_tokens: int | None


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


def _serves(raw: Any, project_id: int) -> bool:
    try:
        projects = json.loads(str(raw or "[]")) if not isinstance(raw, list) else raw
    except (TypeError, ValueError):
        return False
    return isinstance(projects, list) and any(
        str(value) == str(project_id) for value in projects
    )


def machine_capacities(
    conn: Any, *, project_id: int, now: str
) -> tuple[MachineCapacity, ...]:
    """Lanes against cap for every connected machine serving this project.

    Read from the relay rows directly rather than from eligibility, because a
    machine at its cap is exactly the one eligibility drops and exactly the
    one the seat needs to see before it launches.
    """
    p = marker(conn)
    rows = conn.execute(
        "SELECT machine_id, project_checkouts, machine_capacity FROM session_relays "
        f"WHERE connected_until >= {p} AND state IN ('active','idle') "
        "ORDER BY last_seen_at DESC, machine_id",
        (now,),
    ).fetchall()
    found: dict[str, MachineCapacity] = {}
    for row in rows:
        machine_id = str(row["machine_id"])
        if machine_id in found or not _serves(row["project_checkouts"], project_id):
            continue
        found[machine_id] = machine_capacity(
            conn,
            machine_id=machine_id,
            capacity_document=row["machine_capacity"],
            now=now,
        )
    return tuple(found[machine] for machine in sorted(found))


def capacity_line(entry: MachineCapacity) -> str:
    """The one line a seat reads before launching onto this machine."""
    if entry.unreported:
        return (
            f"capacity {entry.summary()}; update that machine's relay to publish "
            "memory, load, and its lane cap"
        )
    verdict = " · AT CAP, launches refuse" if entry.at_capacity else ""
    return f"capacity {entry.summary()} · {entry.cap_origin()}{verdict}"


def live_session_counts(conn: Any, *, project_id: int) -> tuple[SessionCount, ...]:
    """Live sessions grouped by machine, surface, and model selection.

    Probe sessions are excluded through the same shared predicate the
    Sessions page and the Overview band apply, so all three session readers
    answer from one definition instead of leaving this one correct by
    coincidence of its live-only filter.
    """
    p = marker(conn)
    not_probe = not_probe_session_sql("harness_sessions")
    rows = conn.execute(
        f"""SELECT machine_id, executor_surface,
                   requested_model, requested_reasoning_effort,
                   requested_context_window_tokens,
                   model, reasoning_effort, context_window_tokens,
                   COUNT(*) AS n
              FROM harness_sessions
             WHERE ended_at IS NULL AND terminated_at IS NULL
               AND {not_probe}
               AND project_id = {p}
               AND COALESCE(machine_id, '') <> ''
               AND COALESCE(executor_surface, '') <> ''
             GROUP BY machine_id, executor_surface,
                      requested_model, requested_reasoning_effort,
                      requested_context_window_tokens,
                      model, reasoning_effort, context_window_tokens""",
        (int(project_id),),
    ).fetchall()
    return tuple(
        SessionCount(
            machine_id=str(row["machine_id"]),
            surface=str(row["executor_surface"]),
            count=int(row["n"]),
            requested_model=row["requested_model"],
            requested_reasoning_effort=row["requested_reasoning_effort"],
            requested_context_window_tokens=row["requested_context_window_tokens"],
            model=row["model"],
            reasoning_effort=row["reasoning_effort"],
            context_window_tokens=row["context_window_tokens"],
        )
        for row in rows
    )


def live_launch_origin_counts(
    conn: Any, *, project_id: int
) -> tuple[tuple[str, int], ...]:
    """Live sessions by launch origin; unbound sessions count as manual."""
    p = marker(conn)
    rows = conn.execute(
        f"""SELECT COALESCE(l.origin, {p}) AS origin, COUNT(*) AS n
              FROM harness_sessions s
              LEFT JOIN session_launches l ON l.registered_session_id = s.session_id
             WHERE s.ended_at IS NULL AND s.terminated_at IS NULL
               AND s.project_id = {p}
             GROUP BY 1""",
        (MANUAL_SESSION_ORIGIN, int(project_id)),
    ).fetchall()
    counted = {str(row["origin"]): int(row["n"]) for row in rows}
    origins = (*LAUNCH_ORIGINS, MANUAL_SESSION_ORIGIN)
    return tuple((origin, counted.get(origin, 0)) for origin in origins)


__all__ = [
    "MANUAL_SESSION_ORIGIN",
    "SessionCount",
    "SurfaceReadiness",
    "capacity_line",
    "launchable_surfaces",
    "machine_capacities",
    "live_launch_origin_counts",
    "live_session_counts",
]
