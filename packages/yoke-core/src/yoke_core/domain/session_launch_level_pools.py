"""The quota a level option would spend, read from only the pools it draws on.

A surface publishes several meters at once, and a model bills to only some of
them: a Claude model draws on the rolling 5-hour window, the weekly
all-models window, and the weekly window scoped to its own family; a Cursor
model draws on Cursor Models or on Other Models, never both; Codex meters the
whole account weekly. Placement reads exactly the windows that cover the
option's model, so a pool the option will never touch can neither recommend
it nor block it.

An option is blocked only by an affirmative zero that paid extra usage cannot
cover: a readable window covering its model with no included quota left, on a
surface whose fresh extra-usage reading is disabled, capped or unfunded
(:func:`yoke_contracts.session_control.model_billing_pools.included_zero_blocks`).
An unreadable meter, no meter at all, or extra usage that is available,
unknown or stale is not exhaustion.

A pool's headroom assumes one worker spends it, so each pool also carries the
live workers already drawing on it: sessions on the same machine and surface
whose model the window covers, across every project, plus launches placed
there that have not registered yet. A launch in flight is a worker placement
must not count twice, and a burst of launches must see each earlier one.
"""

from __future__ import annotations

from datetime import datetime

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from yoke_contracts.timestamps import parse_instant, temporal_wire
from yoke_contracts.session_control.extra_usage import (
    EXTRA_BLOCKING_STATUSES,
    EXTRA_UNKNOWN,
)
from yoke_core.domain.plan_limit_extra_usage import extra_label_now
from yoke_contracts.session_control.model_billing_pools import (
    extra_usage_status,
    window_covers_model,
)
from yoke_core.domain.session_probe import not_probe_session_sql
from yoke_contracts.session_control.plan_limit_unreadable_guidance import (
    unreadable_guidance,
)
from yoke_core.domain.steering_fleet_plan_capacity import (
    EMPTY,
    compute_plan_limit,
    format_reset_utc,
    window_label,
)
from yoke_core.domain.steering_fleet_report_detectors import marker
from yoke_core.domain.steering_fleet_report_limits import MachinePlanLimit

_IN_FLIGHT_LAUNCH_STATES = ("queued", "assigned", "launching", "awaiting_registration")

#: Live workers keyed by ``(machine_id, surface, model)``.
WorkerCounts = Mapping[tuple[str, str, str], int]


@dataclass(frozen=True)
class PoolCheck:
    """One meter window an option's model draws on, as placement read it."""

    window: str
    remaining_percent: float | None
    headroom_percent: float | None
    resets_at: datetime | None
    status: str
    exhausted: bool
    reason: str | None = None
    workers: int = 0
    #: Extra-usage status as of now, and the shared phrase naming it.
    extra_status: str = EXTRA_UNKNOWN
    extra_label: str = ""

    def __post_init__(self) -> None:
        if self.resets_at is not None:
            object.__setattr__(self, "resets_at", parse_instant(self.resets_at))

    @property
    def resets_utc(self) -> str | None:
        """The reset as the steering report prints it (UTC), or ``None``."""
        text = format_reset_utc(self.resets_at)
        return None if text == EMPTY else text

    @property
    def share_percent(self) -> float | None:
        """Headroom one more worker gets, split evenly with the live workers."""
        if self.headroom_percent is None:
            return None
        return self.headroom_percent / (self.workers + 1)

    def to_dict(self) -> dict[str, Any]:
        out = {
            **temporal_wire(asdict(self)),
            "resets_utc": self.resets_utc,
            "share_percent": self.share_percent,
        }
        if self.status != "ok":
            out["guidance"] = unreadable_guidance(self.reason)
        return out


def pool_workers(
    workers: WorkerCounts, *, machine_id: str, surface: str, scope: str
) -> int:
    """Live workers on this machine and surface whose model ``scope`` covers."""
    return sum(
        count
        for (machine, worker_surface, model), count in workers.items()
        if machine == machine_id
        and worker_surface == surface
        and window_covers_model(surface, model, scope)
    )


def option_pools(
    limits: Sequence[MachinePlanLimit],
    *,
    machine_id: str,
    surface: str,
    model: str,
    now: datetime | str,
    workers: WorkerCounts,
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
        included_empty = bool(readable and float(row.remaining_percent or 0) <= 0)
        extra = extra_usage_status(
            row.extra_usage, observed_at=row.observed_at, now=now
        )
        checks.append(
            PoolCheck(
                window=window_label(row.window_kind, row.scope),
                remaining_percent=row.remaining_percent,
                headroom_percent=computed.headroom_percent,
                resets_at=row.resets_at,
                status=row.status,
                reason=row.reason,
                exhausted=included_empty and extra in EXTRA_BLOCKING_STATUSES,
                workers=pool_workers(
                    workers, machine_id=machine_id, surface=surface, scope=row.scope
                ),
                extra_status=extra,
                extra_label=extra_label_now(row, now=now),
            )
        )
    return tuple(checks)


def binding_pool(pools: Sequence[PoolCheck]) -> PoolCheck | None:
    """The covering window with the least per-worker headroom: the first wall."""
    readable = [pool for pool in pools if pool.share_percent is not None]
    if not readable:
        return None
    return min(readable, key=lambda pool: float(pool.share_percent or 0.0))


def exhausted_pool(pools: Sequence[PoolCheck]) -> PoolCheck | None:
    """The first covering window confirmed empty, or ``None``."""
    return next((pool for pool in pools if pool.exhausted), None)


def live_workers(conn: Any) -> dict[tuple[str, str, str], int]:
    """Live workers per machine, surface and model, launches in flight included."""
    p = marker(conn)
    counts: dict[tuple[str, str, str], int] = {}
    sessions = conn.execute(
        "SELECT COALESCE(machine_id, '') AS machine, executor_surface AS surface, "
        "COALESCE(model, requested_model, '') AS model, COUNT(*) AS n "
        "FROM harness_sessions "
        "WHERE ended_at IS NULL AND terminated_at IS NULL "
        f"AND {not_probe_session_sql('harness_sessions')} "
        "AND COALESCE(executor_surface, '') <> '' "
        "GROUP BY 1, 2, 3"
    ).fetchall()
    holes = ",".join(p for _ in _IN_FLIGHT_LAUNCH_STATES)
    launches = conn.execute(
        "SELECT COALESCE(assigned_machine_id, '') AS machine, "
        "selected_surface AS surface, "
        "COALESCE(resolved_model, requested_model, '') AS model, COUNT(*) AS n "
        "FROM session_launches "
        f"WHERE state IN ({holes}) AND registered_session_id IS NULL "
        "AND COALESCE(selected_surface, '') <> '' "
        "GROUP BY 1, 2, 3",
        _IN_FLIGHT_LAUNCH_STATES,
    ).fetchall()
    for row in [*sessions, *launches]:
        key = (str(row["machine"]), str(row["surface"]), str(row["model"]))
        counts[key] = counts.get(key, 0) + int(row["n"])
    return counts


def surface_workers(workers: WorkerCounts) -> dict[str, int]:
    """Live workers per surface, summed over machines and models."""
    totals: dict[str, int] = {}
    for (_machine, surface, _model), count in workers.items():
        totals[surface] = totals.get(surface, 0) + count
    return totals


__all__ = [
    "PoolCheck",
    "WorkerCounts",
    "binding_pool",
    "exhausted_pool",
    "live_workers",
    "option_pools",
    "pool_workers",
    "surface_workers",
]
