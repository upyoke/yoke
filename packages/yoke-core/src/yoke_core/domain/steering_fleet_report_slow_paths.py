"""Registered functions over their latency budget in the last hour.

A control-plane call that has grown slow shows up first as a release that
stalls, long after the change that slowed it merged. This section names it
while it is happening, on the report the steering seat already reads.

It classifies timings the way the Performance page does — one
:func:`~yoke_core.domain.performance_observations.observation` per
``YokeFunctionCalled`` row, then the same p95 — so the two never disagree on
what a call is. Only the ``function`` family counts. Relay long-polls and
watcher wall time carry ``intentional_wait`` and are long by design, so the
observation's own flag excludes them rather than a list of names.

Events are telemetry. A window with no events reports nothing, and a read
that fails leaves the section out; neither ever fails the report. Rows
attributed to a held project count, and so do rows the dispatcher could
not attribute to any project: a universe's database serves one tenant, and
the rows carry only a function id and a duration.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Sequence

from yoke_contracts.timestamps import parse_instant

from yoke_core.domain import db_backend
from yoke_core.domain.db_savepoint import savepoint
from yoke_core.domain.events_function_index import function_identity_sql
from yoke_core.domain.hook_overhead import _percentile
from yoke_core.domain.performance_observations import observation
from yoke_core.domain.steering_fleet_report_detectors import marker

#: A function whose p95 over the window exceeds this is a slow path.
SLOW_PATH_P95_MS = 5_000
#: A function with any single call longer than this is a slow path.
SLOW_PATH_MAX_MS = 30_000
SLOW_PATH_WINDOW = timedelta(hours=1)

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SlowPath:
    """One function over budget: its timed calls, p95 and longest call."""

    operation: str
    count: int
    p95_ms: int
    max_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "count": self.count,
            "p95_ms": self.p95_ms,
            "max_ms": self.max_ms,
        }


def over_budget(observations: Iterable[dict[str, Any] | None]) -> tuple[SlowPath, ...]:
    """Function operations whose p95 or longest call is over budget."""
    durations: dict[str, list[int]] = defaultdict(list)
    for value in observations:
        if (
            value is None
            or value["family"] != "function"
            or value["intentional_wait"]
            or value["duration_ms"] is None
        ):
            continue
        durations[value["operation"]].append(value["duration_ms"])
    rows = []
    for operation, values in durations.items():
        p95, longest = _percentile(values, 0.95), max(values)
        if p95 > SLOW_PATH_P95_MS or longest > SLOW_PATH_MAX_MS:
            rows.append(SlowPath(operation, len(values), p95, longest))
    return tuple(sorted(rows, key=lambda row: (-row.max_ms, row.operation)))


def read_slow_paths(
    conn: Any, *, project_ids: Sequence[int], now: datetime | str
) -> tuple[SlowPath, ...]:
    """Over-budget functions in the last hour for these projects."""
    if not project_ids:
        return ()
    end = parse_instant(now)
    p = marker(conn)
    holes = ", ".join(p for _ in project_ids)
    sql = (
        "SELECT e.event_id, e.event_name, e.created_at, e.duration_ms, "
        f"{function_identity_sql('e.envelope')} AS function_id "
        f"FROM events e WHERE e.event_name = {p} "
        f"AND e.created_at >= {p} AND e.created_at <= {p} "
        f"AND (e.project_id IN ({holes}) OR e.project_id IS NULL)"
    )
    params = (
        "YokeFunctionCalled",
        end - SLOW_PATH_WINDOW,
        end,
        *(int(project) for project in project_ids),
    )
    try:
        with savepoint(conn, "steering_report_slow_paths", owns=False):
            rows = conn.execute(sql, params).fetchall()
    except db_backend.database_error_types(conn) as exc:
        _log.warning("steering report slow paths unread: %s", exc)
        return ()
    records = [dict(row) for row in rows]
    return over_budget(
        observation(
            {**record, "envelope": {"context": {"function": record["function_id"]}}},
            end,
        )
        for record in records
    )


def _seconds(milliseconds: int) -> str:
    return f"{milliseconds / 1000:.1f}s"


def slow_path_lines(rows: Sequence[SlowPath]) -> list[str]:
    """The report section, or nothing when every function is in budget."""
    if not rows:
        return []
    return [
        (
            f"## slow paths · last {int(SLOW_PATH_WINDOW.total_seconds() // 3600)}h · "
            f"p95 over {_seconds(SLOW_PATH_P95_MS)} or a call over "
            f"{_seconds(SLOW_PATH_MAX_MS)}"
        ),
        *(
            f"  {row.operation}  {row.count} calls · p95 {_seconds(row.p95_ms)}"
            f" · max {_seconds(row.max_ms)}"
            for row in rows
        ),
        "",
    ]


__all__ = [
    "SLOW_PATH_MAX_MS",
    "SLOW_PATH_P95_MS",
    "SLOW_PATH_WINDOW",
    "SlowPath",
    "over_budget",
    "read_slow_paths",
    "slow_path_lines",
]
