"""Hourly client and server cost projection for tool hooks."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from yoke_core.domain import db_backend


HOOK_OVERHEAD_FIELDS = [
    "hour_utc",
    "hook_count",
    "pre_client_p50_ms",
    "pre_client_p90_ms",
    "pre_server_p50_ms",
    "pre_remainder_p50_ms",
    "post_client_p50_ms",
    "post_client_p90_ms",
    "post_server_p50_ms",
    "post_remainder_p50_ms",
    "overhead_per_tool_call_ms",
]
_HOOK_EVENT_KEYS = {"PreToolUse": "pre", "PostToolUse": "post"}


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
        "SELECT hook_event_name, duration_ms, envelope, created_at FROM events "
        f"WHERE event_name={marker} AND created_at >= {marker} "
        "AND hook_event_name IN ('PreToolUse','PostToolUse')",
        ("HookDispatchTelemetry", cutoff),
    ).fetchall()


def hook_overhead_rows(hours: int) -> list[dict[str, Any]]:
    """Return newest-first UTC buckets from canonical dispatch events."""
    cutoff_at = datetime.now(timezone.utc) - timedelta(hours=hours)
    cutoff = cutoff_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "hook_count": 0,
            "pre_client": [],
            "pre_server": [],
            "pre_remainder": [],
            "post_client": [],
            "post_server": [],
            "post_remainder": [],
        }
    )
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
        bucket = grouped[hour.strftime("%Y-%m-%dT%H:00:00Z")]
        bucket["hook_count"] += 1
        server_ms = max(0, int(_value(row, "duration_ms", 1) or 0))
        bucket[f"{hook_key}_server"].append(server_ms)
        try:
            envelope = json.loads(_value(row, "envelope", 2) or "{}")
            context = envelope.get("context", {})
            client_ms = context.get("client_wall_ms")
        except (AttributeError, TypeError, ValueError):
            continue
        if isinstance(client_ms, bool) or not isinstance(client_ms, int):
            continue
        client_ms = max(server_ms, client_ms)
        bucket[f"{hook_key}_client"].append(client_ms)
        bucket[f"{hook_key}_remainder"].append(client_ms - server_ms)

    result = []
    for hour, bucket in sorted(grouped.items(), reverse=True):
        row = {"hour_utc": hour, "hook_count": bucket["hook_count"]}
        for hook_key in ("pre", "post"):
            clients = bucket[f"{hook_key}_client"]
            row[f"{hook_key}_client_p50_ms"] = _percentile(clients, 0.50)
            row[f"{hook_key}_client_p90_ms"] = _percentile(clients, 0.90)
            row[f"{hook_key}_server_p50_ms"] = _percentile(
                bucket[f"{hook_key}_server"], 0.50
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


__all__ = ["HOOK_OVERHEAD_FIELDS", "hook_overhead_rows"]
