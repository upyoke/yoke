"""Interpret existing event timing owners without inventing missing measurements."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from yoke_contracts.timestamps import as_utc

from yoke_core.domain.hook_overhead import _duration, _timestamp
from yoke_core.domain.hook_overhead_tool import _classify_call
from yoke_core.domain.observe_timing import delivery_is_pending

TOOL_EVENTS = (
    "HarnessToolCallCompleted",
    "HarnessToolCallFailed",
    "HarnessToolCallStructuredExit",
    "HarnessLifecycleMutationDetected",
)
TIMING_EVENTS = ("YokeFunctionCalled", "HookDispatchTelemetry", *TOOL_EVENTS)
FAMILIES = ("function", "tool", "hook", "relay", "watcher")

# Recognize an operation, never a duration. Shell text alone is evidence of a
# watcher invocation, not evidence of how much of its wall time was polling.
WATCHER_COMMAND = re.compile(
    r"(?:^|[\s;])yoke\s+(?:--env\s+\S+\s+)?(?:dev\s+run\s+--\s+yoke\s+)?watch\s+(pytest|merge|deploy|fleet|preflight|qa-case|qa-plan|ci-run|doctor|tail)\b"
)


def event_context(envelope: Any) -> dict[str, Any]:
    try:
        value = json.loads(envelope) if isinstance(envelope, str) else envelope
        context = (value or {}).get("context", {})
        detail = context.get("detail")
        return detail if isinstance(detail, dict) else context
    except (ValueError, TypeError, AttributeError):
        return {}


def observation(row: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    now = as_utc(now)
    observed = _timestamp(row.get("created_at"))
    if observed is None:
        return None
    context = event_context(row.get("envelope"))
    name = row["event_name"]
    duration = _duration(row.get("duration_ms"))
    family = "function"
    status = "timed" if duration is not None else "unknown"
    identity = context.get("function") or name
    breakdown: dict[str, Any] = {}
    command = row.get("command_summary")
    harness = row.get("executor") or context.get("executor") or None
    if name in TOOL_EVENTS:
        family = "watcher" if command and WATCHER_COMMAND.search(command) else "tool"
        identity = row.get("tool_name") or "Unknown tool"
        duration, status = _classify_call(
            event_duration=duration,
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
            observed=observed,
            now=now,
            harness=harness or "",
            tool_name=row.get("tool_name") or "",
            tool_use_id=row.get("tool_use_id"),
        )
        breakdown["tool_wall_ms"] = duration
        completed = _timestamp(row.get("completed_at"))
        breakdown["delivery_lag_ms"] = (
            max(0, round((observed - completed).total_seconds() * 1000))
            if completed
            else None
        )
    elif name == "HookDispatchTelemetry":
        family = "hook"
        identity = row.get("hook_event_name") or "Unknown hook"
        client = _duration(context.get("client_wall_ms"))
        if duration is None and delivery_is_pending(observed, now=now):
            status = "pending"
        breakdown = {"evaluator_ms": duration, "client_wall_ms": client}
        # The evaluator is nested in the client wall. Do not add them.
        breakdown["client_remainder_ms"] = (
            client - duration
            if client is not None and duration is not None and client >= duration
            else None
        )
    elif identity == "session_control.relay.claim":
        family = "relay"
        breakdown["long_poll_wall_ms"] = duration
    else:
        breakdown["handler_ms"] = duration
    return {
        "event_id": str(row["event_id"]),
        "observed_at": observed,
        "family": family,
        "duration_ms": duration,
        "timing_status": status,
        "operation": str(identity),
        "command_summary": command,
        "harness": harness,
        "surface": row.get("executor_surface") or None,
        "machine": row.get("machine_id") or None,
        "outcome": row.get("event_outcome") or None,
        "session_id": row.get("session_id"),
        "tool_use_id": row.get("tool_use_id"),
        "trace_id": row.get("trace_id"),
        "project_id": row.get("project_id"),
        "intentional_wait": family in ("relay", "watcher"),
        "wait_reason": {
            "relay": "relay long-poll operation",
            "watcher": "watcher invocation wall time",
        }.get(family),
        "breakdown": breakdown,
        "unavailable_spans": (
            ["queue", "auth", "database", "external_dependencies"]
            if family in ("function", "relay")
            else []
        ),
        "span_coverage": (
            "Only the handler timer is retained for this request; queue, auth, "
            "database and external waits were not recorded in its event. "
            "The handler duration cannot attribute its internal work."
            if family in ("function", "relay")
            else "Existing owner timings shown below; nested timings are not additive."
        ),
    }


def unique_observations(
    rows: list[dict[str, Any]], now: datetime
) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result = []
    for row in rows:
        if (
            row["event_name"] in TOOL_EVENTS
            and row.get("session_id")
            and row.get("tool_use_id")
        ):
            key = (row["session_id"], row["tool_use_id"])
            if key in seen:
                continue
            seen.add(key)
        value = observation(row, now)
        if value is not None:
            result.append(value)
    return result
