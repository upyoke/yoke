"""Tool-duration coverage: measured, unsupported Cursor shell, or unknown."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from yoke_contracts.cursor_shell_timing import (
    CURSOR_SHELL_TIMING_UNSUPPORTED_REASON,
    is_unsupported_cursor_shell_duration,
)
from yoke_core.domain import db_backend
from yoke_core.domain.hook_overhead import (
    _coverage,
    _duration,
    _executor,
    _mean,
    _percentile,
    _timestamp,
    _value,
)
from yoke_core.domain.observe_timing import (
    TIMING_MEASURED,
    TIMING_PENDING_START_DELIVERY,
    report_owner_elapsed,
)

TOOL_LATENCY_FIELDS = [
    "hour_utc",
    "scope",
    "harness",
    "surfaces",
    "call_count",
    "timed_count",
    "pending_count",
    "unsupported_count",
    "unknown_count",
    "timing_coverage_pct",
    "unsupported_timing_reason",
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


def _tool_metric_rows(conn: Any, cutoff: str) -> list[Any]:
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ",".join(marker for _ in _TOOL_COMPLETION_EVENTS)
    return conn.execute(
        "SELECT e.duration_ms, e.envelope, e.created_at, e.session_id, "
        "COALESCE(hs.executor, ''), COALESCE(hs.executor_surface, ''), "
        "e.tool_name, e.tool_use_id, stc.started_at, stc.completed_at "
        "FROM events e LEFT JOIN harness_sessions hs "
        "ON hs.session_id=e.session_id "
        "LEFT JOIN session_tool_calls stc "
        "ON stc.session_id=e.session_id AND stc.tool_use_id=e.tool_use_id "
        f"WHERE e.event_name IN ({placeholders}) AND e.created_at >= {marker}",
        (*_TOOL_COMPLETION_EVENTS, cutoff),
    ).fetchall()


def _tool_status(
    timed: int, pending: int, unsupported: int, unknown: int, total: int
) -> str:
    if unknown:
        return "incomplete"
    if pending:
        return "pending"
    if total and timed == 0 and unsupported == total:
        return "unsupported"
    return "comparable" if total else "incomplete"


def _classify_call(
    *,
    event_duration: int | None,
    started_at: Any,
    completed_at: Any,
    observed: datetime,
    now: datetime,
    harness: str,
    tool_name: str,
    tool_use_id: str | None,
) -> tuple[int | None, str]:
    """Return (milliseconds, kind) using owner timestamps when a row exists."""
    owner_present = started_at is not None or completed_at is not None
    if owner_present:
        measurement = report_owner_elapsed(
            started_at, completed_at, observed_at=observed, now=now
        )
        if measurement.status == TIMING_MEASURED:
            return measurement.milliseconds, "timed"
        if measurement.status == TIMING_PENDING_START_DELIVERY:
            return None, "pending"
        return None, "unknown"
    if event_duration is not None:
        return event_duration, "timed"
    if is_unsupported_cursor_shell_duration(
        harness=harness,
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        duration_ms=event_duration,
    ):
        return None, "unsupported"
    measurement = report_owner_elapsed(None, None, observed_at=observed, now=now)
    if measurement.status == TIMING_PENDING_START_DELIVERY:
        return None, "pending"
    return None, "unknown"


def _unique_calls(rows: list[Any]) -> list[Any]:
    """Count one call per ``(session_id, tool_use_id)``; ID-less events stay 1:1."""
    seen: dict[tuple[str, str, str], Any] = {}
    unique: list[Any] = []
    for index, row in enumerate(rows):
        session_id = str(_value(row, "session_id", 3) or "").strip()
        tool_use_id = str(_value(row, "tool_use_id", 7) or "").strip()
        key = (
            ("call", session_id, tool_use_id)
            if session_id and tool_use_id
            else ("event", str(index), "")
        )
        if key in seen:
            continue
        seen[key] = row
        unique.append(row)
    return unique


def tool_latency_rows(hours: int) -> list[dict[str, Any]]:
    """Return tool-duration means with timed/total coverage.

    Reports read repaired ``session_tool_calls`` endpoints, not the stale
    ingest snapshot on the event. Unsupported Cursor shell gaps stay in the
    denominator. Pending start delivery is named separately from unknown.
    Duplicate completion events for one call identity count once.
    """
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    grouped: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "total": 0,
            "durations": [],
            "pending": 0,
            "unsupported": 0,
            "sessions": set(),
            "surfaces": set(),
        }
    )
    conn = db_backend.connect()
    try:
        rows = _unique_calls(_tool_metric_rows(conn, cutoff))
    finally:
        conn.close()
    for row in rows:
        observed = _timestamp(_value(row, "created_at", 2))
        if observed is None:
            continue
        hour_key = observed.replace(minute=0, second=0, microsecond=0).strftime(
            "%Y-%m-%dT%H:00:00Z"
        )
        envelope = _value(row, "envelope", 1)
        harness = str(_value(row, "executor", 4) or "").strip() or _executor(envelope)
        surface = str(_value(row, "executor_surface", 5) or "").strip()
        session_id = str(_value(row, "session_id", 3) or "").strip()
        tool_use_id = str(_value(row, "tool_use_id", 7) or "").strip() or None
        duration, kind = _classify_call(
            event_duration=_duration(_value(row, "duration_ms", 0)),
            started_at=_value(row, "started_at", 8),
            completed_at=_value(row, "completed_at", 9),
            observed=observed,
            now=now,
            harness=harness,
            tool_name=str(_value(row, "tool_name", 6) or "").strip(),
            tool_use_id=tool_use_id,
        )
        for scope, group_harness in (("global", "all"), ("harness", harness)):
            bucket = grouped[(hour_key, scope, group_harness)]
            bucket["total"] += 1
            if kind == "timed" and duration is not None:
                bucket["durations"].append(duration)
            elif kind == "pending":
                bucket["pending"] += 1
            elif kind == "unsupported":
                bucket["unsupported"] += 1
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
        pending_count = bucket["pending"]
        unsupported_count = bucket["unsupported"]
        unknown_count = total - timed - pending_count - unsupported_count
        result.append(
            {
                "hour_utc": hour,
                "scope": scope,
                "harness": harness or "unknown",
                "surfaces": sorted(bucket["surfaces"]),
                "call_count": total,
                "timed_count": timed,
                "pending_count": pending_count,
                "unsupported_count": unsupported_count,
                "unknown_count": unknown_count,
                "timing_coverage_pct": _coverage(timed, total),
                "unsupported_timing_reason": (
                    CURSOR_SHELL_TIMING_UNSUPPORTED_REASON if unsupported_count else ""
                ),
                "mean_ms": _mean(bucket["durations"]),
                "p95_ms": _percentile(bucket["durations"], 0.95),
                "tool_active_session_count": len(bucket["sessions"]),
                "comparison_status": _tool_status(
                    timed, pending_count, unsupported_count, unknown_count, total
                ),
            }
        )
    return result


__all__ = ["TOOL_LATENCY_FIELDS", "tool_latency_rows"]
