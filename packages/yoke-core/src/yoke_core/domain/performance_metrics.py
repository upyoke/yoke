"""Exact observation-weighted buckets for the Performance chart."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from yoke_core.domain.hook_overhead import _percentile
from yoke_core.domain.performance_observations import FAMILIES

MAX_POINTS = 800
MIN_BUCKET_SECONDS = 60


def bucket_seconds(start: float, end: float, points: int) -> int:
    # A minute is useful for event-level timings; never invent observations
    # between buckets. Round upwards, preserving the requested point bound.
    return max(MIN_BUCKET_SECONDS, math.ceil((end - start) / points / 60) * 60)


def aggregate(
    observations: list[dict[str, Any]], start: float, end: float, points: int
) -> dict[str, Any]:
    seconds = bucket_seconds(start, end, points)
    count = math.ceil((end - start) / seconds)
    groups: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for value in observations:
        index = int((value["timestamp"] - start) // seconds)
        if 0 <= index < count:
            groups[index, value["family"]].append(value)
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
                "start": start + index * seconds,
                "end": min(end, start + (index + 1) * seconds),
                "metrics": metrics,
            }
        )
    return {
        "buckets": buckets,
        "bucket_seconds": seconds,
        "observation_count": len(observations),
        "last_observation": max((v["observed_at"] for v in observations), default=None),
    }
