"""Exact observation-weighted buckets for the Performance chart."""

from __future__ import annotations

from datetime import datetime, timedelta

from yoke_contracts.timestamps import as_utc
from collections import defaultdict
from typing import Any

from yoke_core.domain.hook_overhead import _percentile
from yoke_core.domain.performance_observations import FAMILIES

MAX_POINTS = 800
MIN_BUCKET_SECONDS = 60


def bucket_seconds(start: datetime, end: datetime, points: int) -> int:
    # Round upward in whole minutes using exact timedelta arithmetic. Numeric
    # seconds describe bucket resolution, never the observation's instant.
    start, end = as_utc(start), as_utc(end)
    if start >= end or points <= 0:
        raise ValueError("performance_range_invalid")
    minutes, remainder = divmod(
        end - start, timedelta(seconds=MIN_BUCKET_SECONDS) * points
    )
    return max(1, minutes + bool(remainder)) * MIN_BUCKET_SECONDS


def aggregate(
    observations: list[dict[str, Any]], start: datetime, end: datetime, points: int
) -> dict[str, Any]:
    start, end = as_utc(start), as_utc(end)
    seconds = bucket_seconds(start, end, points)
    width = timedelta(seconds=seconds)
    count, remainder = divmod(end - start, width)
    count += bool(remainder)
    groups: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    retained = []
    for value in observations:
        observed = as_utc(value["observed_at"])
        if start <= observed < end:
            index = (observed - start) // width
            groups[index, value["family"]].append(value)
            retained.append(observed)
    buckets = []
    for index in range(count):
        metrics = {}
        for family in FAMILIES:
            values = groups[index, family]
            durations = [
                value["duration_ms"]
                for value in values
                if value["duration_ms"] is not None
            ]
            metrics[family] = {
                "count": len(values),
                "timed_count": len(durations),
                "unknown_count": sum(v["timing_status"] == "unknown" for v in values),
                "pending_count": sum(v["timing_status"] == "pending" for v in values),
                "unsupported_count": sum(
                    v["timing_status"] == "unsupported" for v in values
                ),
                "sum_ms": sum(durations) if durations else None,
                "avg_ms": sum(durations) / len(durations) if durations else None,
                "p95_ms": _percentile(durations, 0.95),
                "resolution_seconds": seconds,
            }
        buckets.append(
            {
                "start": start + index * width,
                "end": min(end, start + (index + 1) * width),
                "metrics": metrics,
            }
        )
    return {
        "buckets": buckets,
        "bucket_seconds": seconds,
        "observation_count": len(retained),
        "last_observation": max(retained, default=None),
    }
