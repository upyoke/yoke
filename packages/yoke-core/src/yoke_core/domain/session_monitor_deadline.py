"""Project Monitor subscription deadlines onto their durable tool-call owner."""

from datetime import timedelta
from typing import Any

from yoke_contracts.harness_wake_capability import wake_capability_for_mechanism
from yoke_contracts.hook_runner.client_facts import headless_launch
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.schema_common import _get_columns


def monitor_timeout_seconds(payload: dict) -> float | None:
    if payload.get("tool_name") != "Monitor":
        return None
    capability = wake_capability_for_mechanism("Monitor")
    assert capability is not None
    limit = capability.subscription_limit_seconds(headless=headless_launch(payload))
    tool_input = payload.get("tool_input")
    requested = tool_input.get("timeout_ms") if isinstance(tool_input, dict) else None
    if requested is None:
        return capability.idle_wake_default_timeout_seconds
    try:
        seconds = max(int(requested), 0) / 1000
    except (TypeError, ValueError, OverflowError):
        return capability.idle_wake_default_timeout_seconds
    return min(seconds, limit) if limit is not None else seconds


def stamp_monitor_deadline(conn: Any, envelope: dict) -> None:
    """Keep the earliest effective deadline across replay and reordered starts."""
    seconds = envelope.get("monitor_timeout_seconds")
    if seconds is None or "monitor_deadline_at" not in _get_columns(
        conn, "session_tool_calls"
    ):
        return
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    identity = (envelope["session_id"], envelope["tool_use_id"])
    row = conn.execute(
        f"SELECT started_at FROM session_tool_calls WHERE session_id={p} "
        f"AND tool_use_id={p}",
        identity,
    ).fetchone()
    if row is None:
        return
    deadline = instant_parameter(
        conn, parse_instant(row["started_at"]) + timedelta(seconds=seconds)
    )
    conn.execute(
        f"UPDATE session_tool_calls SET monitor_deadline_at={p} "
        f"WHERE session_id={p} AND tool_use_id={p} "
        f"AND (monitor_deadline_at IS NULL OR monitor_deadline_at>{p})",
        (deadline, *identity, deadline),
    )
