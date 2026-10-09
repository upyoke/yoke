"""The quota a level option would spend, read from only the pools it draws on.

A surface publishes several meters at once, and a model bills to only some of
them: a Claude model draws on the rolling 5-hour window, the weekly
all-models window, and the weekly window scoped to its own family; a Cursor
model draws on Cursor Models or on Other Models, never both; Codex meters the
whole account weekly. Placement reads exactly the windows that cover the
option's model, so a pool the option will never touch can neither recommend
it nor block it.

An option is blocked only by an affirmative zero: a readable window covering
its model with no quota left. An unreadable meter, or no meter at all, is
unknown capacity, and unknown is never exhaustion.

Live workers are counted per surface across every project, plus launches
already placed there that have not registered yet, because the spread rule
keeps a worker on every surface and a launch in flight is a worker it must
not place twice.
"""

from __future__ import annotations

from datetime import datetime

from dataclasses import asdict, dataclass
from typing import Any, Sequence

from yoke_contracts.timestamps import parse_instant, temporal_wire
from yoke_contracts.session_control.model_billing_pools import window_covers_model
from yoke_core.domain.session_probe import not_probe_session_sql
from yoke_core.domain.steering_fleet_plan_capacity import (
    compute_plan_limit,
    window_label,
)
from yoke_core.domain.steering_fleet_report_detectors import marker
from yoke_core.domain.steering_fleet_report_limits import MachinePlanLimit

_IN_FLIGHT_LAUNCH_STATES = ("queued", "assigned", "launching", "awaiting_registration")


@dataclass(frozen=True)
class PoolCheck:
    """One meter window an option's model draws on, as placement read it."""

    window: str
    remaining_percent: float | None
    headroom_percent: float | None
    resets_at: datetime | None
    status: str
    exhausted: bool

    def __post_init__(self) -> None:
        if self.resets_at is not None:
            object.__setattr__(self, "resets_at", parse_instant(self.resets_at))

    def to_dict(self) -> dict[str, Any]:
        return temporal_wire(asdict(self))


def option_pools(
    limits: Sequence[MachinePlanLimit],
    *,
    machine_id: str,
    surface: str,
    model: str,
    now: datetime | str,
) -> tuple[PoolCheck, ...]:
    """Every published window on this machine and surface covering ``model``."""
    checks: list[PoolCheck] = []
    for row in limits:
        if row.machine_id != machine_id or row.surface != surface:
            continue
        if not window_covers_model(surface, model, row.scope):
            continue
        computed = compute_plan_limit(row, now=now)
        readable = row.status == "ok" and row.remaining_percent is not None
        checks.append(
            PoolCheck(
                window=window_label(row.window_kind, row.scope),
                remaining_percent=row.remaining_percent,
                headroom_percent=computed.headroom_percent,
                resets_at=row.resets_at,
                status=row.status,
                exhausted=bool(readable and float(row.remaining_percent or 0) <= 0),
            )
        )
    return tuple(checks)


def binding_pool(pools: Sequence[PoolCheck]) -> PoolCheck | None:
    """The covering window with the least readable headroom: the first wall."""
    readable = [pool for pool in pools if pool.headroom_percent is not None]
    if not readable:
        return None
    return min(readable, key=lambda pool: float(pool.headroom_percent or 0.0))


def exhausted_pool(pools: Sequence[PoolCheck]) -> PoolCheck | None:
    """The first covering window confirmed empty, or ``None``."""
    return next((pool for pool in pools if pool.exhausted), None)


def live_workers(conn: Any) -> dict[str, int]:
    """Live workers per surface, launches in flight included."""
    p = marker(conn)
    counts: dict[str, int] = {}
    sessions = conn.execute(
        "SELECT executor_surface AS surface, COUNT(*) AS n FROM harness_sessions "
        "WHERE ended_at IS NULL AND terminated_at IS NULL "
        f"AND {not_probe_session_sql('harness_sessions')} "
        "AND COALESCE(executor_surface, '') <> '' "
        "GROUP BY executor_surface"
    ).fetchall()
    holes = ",".join(p for _ in _IN_FLIGHT_LAUNCH_STATES)
    launches = conn.execute(
        "SELECT selected_surface AS surface, COUNT(*) AS n "
        "FROM session_launches "
        f"WHERE state IN ({holes}) AND registered_session_id IS NULL "
        "AND COALESCE(selected_surface, '') <> '' "
        "GROUP BY selected_surface",
        _IN_FLIGHT_LAUNCH_STATES,
    ).fetchall()
    for row in [*sessions, *launches]:
        key = str(row["surface"])
        counts[key] = counts.get(key, 0) + int(row["n"])
    return counts


__all__ = [
    "PoolCheck",
    "binding_pool",
    "exhausted_pool",
    "live_workers",
    "option_pools",
]
