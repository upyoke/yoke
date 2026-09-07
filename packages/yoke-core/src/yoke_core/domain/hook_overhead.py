"""Hourly hook-latency projection with explicit timing coverage."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from yoke_core.domain import db_backend


HOOK_OVERHEAD_FIELDS = [
    "hour_utc",
    "scope",
    "harness",
    "surfaces",
    "hook_count",
    "tool_active_session_count",
    "evaluator_timed_count",
    "evaluator_timing_coverage_pct",
    "client_timed_count",
    "client_timing_coverage_pct",
    "comparison_status",
    "pre_client_p50_ms",
    "pre_client_p90_ms",
    "pre_client_mean_ms",
    "pre_evaluator_p50_ms",
    "pre_remainder_p50_ms",
    "post_client_p50_ms",
    "post_client_p90_ms",
    "post_client_mean_ms",
    "post_evaluator_p50_ms",
    "post_remainder_p50_ms",
    "overhead_per_tool_call_ms",
]
_HOOK_EVENT_KEYS = {"PreToolUse": "pre", "PostToolUse": "post"}
TOOL_LATENCY_FIELDS = [
    "hour_utc",
    "scope",
    "harness",
    "surfaces",
    "call_count",
    "timed_count",
    "timing_coverage_pct",
    "mean_ms",
    "p95_ms",
    "tool_active_session_count",
    "comparison_status",
]
_TOOL_COMPLETION_EVENTS = (
    "HarnessToolCallCompleted",
    "HarnessToolCallFailed",
    "HarnessToolCallStructuredExit",
    "HarnessLifecycleMutationDetected",
)


def _value(row: Any, key: str, index: int) -> Any:
    return row.get(key) if isinstance(row, dict) else row[index]


def _timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * fraction
    lower, upper = math.floor(rank), math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    interpolated = ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)
    return int(round(interpolated))


def _metric_rows(conn: Any, cutoff: str) -> list[Any]:
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    return conn.execute(
        "SELECT e.hook_event_name, e.duration_ms, e.envelope, e.created_at, "
        "e.session_id, COALESCE(hs.executor_surface, '') "
        "FROM events e LEFT JOIN harness_sessions hs "
        "ON hs.session_id=e.session_id "
        f"WHERE e.event_name={marker} AND e.created_at >= {marker} "
        "AND e.hook_event_name IN ('PreToolUse','PostToolUse')",
        ("HookDispatchTelemetry", cutoff),
    ).fetchall()


def _duration(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _mean(values: list[int]) -> int | None:
    return int(round(sum(values) / len(values))) if values else None


def _coverage(timed: int, total: int) -> float:
    return round(timed * 100.0 / total, 1) if total else 0.0


def _new_bucket() -> dict[str, Any]:
    return {
        "hook_count": 0,
        "sessions": set(),
        "surfaces": set(),
        "pre_total": 0,
        "post_total": 0,
        "pre_client": [],
        "pre_evaluator": [],
        "pre_remainder": [],
        "post_client": [],
        "post_evaluator": [],
        "post_remainder": [],
    }


def _executor(envelope: Any) -> str:
    try:
        context = json.loads(envelope or "{}").get("context", {})
        value = context.get("executor")
    except (AttributeError, TypeError, ValueError):
        return "unknown"
    return str(value).strip() or "unknown"


def hook_overhead_rows(hours: int) -> list[dict[str, Any]]:
    """Return global and per-harness UTC buckets from dispatch events.

    Missing durations stay absent from latency statistics and are counted in
    coverage. A real zero remains a timed value. ``tool_active_session_count``
    is the distinct-session count that emitted a hook in the hour; it is a
    load proxy, not proof those sessions executed simultaneously.
    """
    cutoff_at = datetime.now(timezone.utc) - timedelta(hours=hours)
    cutoff = cutoff_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    grouped: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(_new_bucket)
    conn = db_backend.connect()
    try:
        rows = _metric_rows(conn, cutoff)
    finally:
        conn.close()
    for row in rows:
        observed = _timestamp(_value(row, "created_at", 3))
        hook_key = _HOOK_EVENT_KEYS.get(str(_value(row, "hook_event_name", 0)))
        if observed is None or hook_key is None:
            continue
        hour = observed.replace(minute=0, second=0, microsecond=0)
        hour_key = hour.strftime("%Y-%m-%dT%H:00:00Z")
        envelope = _value(row, "envelope", 2)
        harness = _executor(envelope)
        surface = str(_value(row, "executor_surface", 5) or "").strip()
        session_id = str(_value(row, "session_id", 4) or "").strip()
        evaluator_ms = _duration(_value(row, "duration_ms", 1))
        try:
            context = json.loads(envelope or "{}").get("context", {})
            client_ms = _duration(context.get("client_wall_ms"))
        except (AttributeError, TypeError, ValueError):
            client_ms = None
        for scope, group_harness in (("global", "all"), ("harness", harness)):
            bucket = grouped[(hour_key, scope, group_harness)]
            bucket["hook_count"] += 1
            bucket[f"{hook_key}_total"] += 1
            if session_id:
                bucket["sessions"].add(session_id)
            if surface:
                bucket["surfaces"].add(surface)
            if evaluator_ms is not None:
                bucket[f"{hook_key}_evaluator"].append(evaluator_ms)
            if client_ms is not None:
                comparable_client_ms = (
                    max(evaluator_ms, client_ms)
                    if evaluator_ms is not None
                    else client_ms
                )
                bucket[f"{hook_key}_client"].append(comparable_client_ms)
                if evaluator_ms is not None:
                    bucket[f"{hook_key}_remainder"].append(
                        comparable_client_ms - evaluator_ms
                    )

    result = []
    for (hour, scope, harness), bucket in sorted(
        grouped.items(),
        key=lambda pair: (pair[0][0], pair[0][1] == "global", pair[0][2]),
        reverse=True,
    ):
        evaluator_timed = len(bucket["pre_evaluator"]) + len(bucket["post_evaluator"])
        client_timed = len(bucket["pre_client"]) + len(bucket["post_client"])
        total = bucket["hook_count"]
        complete = (
            total > 0
            and evaluator_timed == total
            and client_timed == total
            and bucket["pre_total"] == bucket["post_total"]
        )
        row = {
            "hour_utc": hour,
            "scope": scope,
            "harness": harness,
            "surfaces": sorted(bucket["surfaces"]),
            "hook_count": total,
            "tool_active_session_count": len(bucket["sessions"]),
            "evaluator_timed_count": evaluator_timed,
            "evaluator_timing_coverage_pct": _coverage(evaluator_timed, total),
            "client_timed_count": client_timed,
            "client_timing_coverage_pct": _coverage(client_timed, total),
            "comparison_status": "comparable" if complete else "incomplete",
        }
        for hook_key in ("pre", "post"):
            clients = bucket[f"{hook_key}_client"]
            row[f"{hook_key}_client_p50_ms"] = _percentile(clients, 0.50)
            row[f"{hook_key}_client_p90_ms"] = _percentile(clients, 0.90)
            row[f"{hook_key}_client_mean_ms"] = _mean(clients)
            row[f"{hook_key}_evaluator_p50_ms"] = _percentile(
                bucket[f"{hook_key}_evaluator"], 0.50
            )
            row[f"{hook_key}_remainder_p50_ms"] = _percentile(
                bucket[f"{hook_key}_remainder"], 0.50
            )
        pre = row["pre_client_p50_ms"]
        post = row["post_client_p50_ms"]
        row["overhead_per_tool_call_ms"] = (
            pre + post if pre is not None and post is not None else None
        )
        result.append(row)
    return result


def _tool_metric_rows(conn: Any, cutoff: str) -> list[Any]:
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ",".join(marker for _ in _TOOL_COMPLETION_EVENTS)
    return conn.execute(
        "SELECT e.duration_ms, e.envelope, e.created_at, e.session_id, "
        "COALESCE(hs.executor, ''), COALESCE(hs.executor_surface, '') "
        "FROM events e LEFT JOIN harness_sessions hs "
        "ON hs.session_id=e.session_id "
        f"WHERE e.event_name IN ({placeholders}) AND e.created_at >= {marker}",
        (*_TOOL_COMPLETION_EVENTS, cutoff),
    ).fetchall()


def tool_latency_rows(hours: int) -> list[dict[str, Any]]:
    """Return tool-duration means with timed/total coverage.

    The denominator is every observed completion, including failures and
    structured exits. Calls with no duration remain in the denominator but do
    not enter the mean or p95; a measured zero does both.
    """
    cutoff_at = datetime.now(timezone.utc) - timedelta(hours=hours)
    cutoff = cutoff_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    grouped: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(
        lambda: {"total": 0, "durations": [], "sessions": set(), "surfaces": set()}
    )
    conn = db_backend.connect()
    try:
        rows = _tool_metric_rows(conn, cutoff)
    finally:
        conn.close()
    for row in rows:
        observed = _timestamp(_value(row, "created_at", 2))
        if observed is None:
            continue
        hour = observed.replace(minute=0, second=0, microsecond=0)
        hour_key = hour.strftime("%Y-%m-%dT%H:00:00Z")
        envelope = _value(row, "envelope", 1)
        stored_harness = str(_value(row, "executor", 4) or "").strip()
        envelope_harness = _executor(envelope)
        harness = stored_harness or envelope_harness
        surface = str(_value(row, "executor_surface", 5) or "").strip()
        session_id = str(_value(row, "session_id", 3) or "").strip()
        duration = _duration(_value(row, "duration_ms", 0))
        for scope, group_harness in (("global", "all"), ("harness", harness)):
            bucket = grouped[(hour_key, scope, group_harness)]
            bucket["total"] += 1
            if duration is not None:
                bucket["durations"].append(duration)
            if session_id:
                bucket["sessions"].add(session_id)
            if surface:
                bucket["surfaces"].add(surface)

    result = []
    for (hour, scope, harness), bucket in sorted(
        grouped.items(),
        key=lambda pair: (pair[0][0], pair[0][1] == "global", pair[0][2]),
        reverse=True,
    ):
        total = bucket["total"]
        timed = len(bucket["durations"])
        result.append(
            {
                "hour_utc": hour,
                "scope": scope,
                "harness": harness or "unknown",
                "surfaces": sorted(bucket["surfaces"]),
                "call_count": total,
                "timed_count": timed,
                "timing_coverage_pct": _coverage(timed, total),
                "mean_ms": _mean(bucket["durations"]),
                "p95_ms": _percentile(bucket["durations"], 0.95),
                "tool_active_session_count": len(bucket["sessions"]),
                "comparison_status": (
                    "comparable" if total > 0 and timed == total else "incomplete"
                ),
            }
        )
    return result


__all__ = [
    "HOOK_OVERHEAD_FIELDS",
    "TOOL_LATENCY_FIELDS",
    "hook_overhead_rows",
    "tool_latency_rows",
]
