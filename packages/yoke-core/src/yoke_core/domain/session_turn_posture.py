"""Durable native-turn posture with order-aware lifecycle updates."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _get_columns


TURN_POSTURES = frozenset({"running", "waiting", "unknown"})
TURN_POSTURE_COLUMN_DDL = (
    "TEXT NOT NULL DEFAULT 'unknown' "
    "CHECK(turn_posture IN ('running','waiting','unknown'))"
)
TURN_POSTURE_AT_COLUMN_DDL = "TEXT DEFAULT NULL"

_WAITING_HOOK_EVENTS = frozenset({"Stop", "SessionEnd"})
_RUNNING_HOOK_EVENTS = frozenset({"UserPromptSubmit"})


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _posture_columns_present(conn: Any) -> bool:
    try:
        columns = set(_get_columns(conn, "harness_sessions"))
    except db_backend.operational_error_types(conn):
        return False
    return {"turn_posture", "turn_posture_at"}.issubset(columns)


def posture_timestamp(value: datetime) -> str:
    """Return a fixed-width UTC timestamp suitable for atomic ordering."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def accepted_hook_posture(
    event_name: str,
    *,
    final_outcome: str,
    timed_out: bool,
    failed: bool,
) -> str | None:
    """Map only a fully accepted aggregate hook result onto native posture."""
    if final_outcome != "allow" or timed_out or failed:
        return None
    if event_name in _WAITING_HOOK_EVENTS:
        return "waiting"
    if event_name in _RUNNING_HOOK_EVENTS:
        return "running"
    return None


def stamp_turn_posture(
    conn: Any,
    *,
    session_id: str,
    posture: str,
    observed_at: datetime,
) -> bool:
    """Apply a posture observation unless a newer observation already won.

    Hook ingress time, rather than completion time, makes a slow Stop unable to
    overwrite a newer prompt. At an exact timestamp tie ``running`` wins, which
    keeps a prompt/tool observation from being hidden by concurrent teardown.
    The update intentionally does not inspect claims, chain state, or ended_at.
    """
    if posture not in TURN_POSTURES:
        raise ValueError(f"invalid turn posture: {posture!r}")
    if not session_id or not _posture_columns_present(conn):
        return False
    marker = _p(conn)
    stamp = posture_timestamp(observed_at)
    cursor = conn.execute(
        "UPDATE harness_sessions SET turn_posture="
        + marker
        + ",turn_posture_at="
        + marker
        + " WHERE session_id="
        + marker
        + " AND (turn_posture_at IS NULL OR turn_posture_at<"
        + marker
        + " OR (turn_posture_at="
        + marker
        + " AND "
        + marker
        + "='running' AND turn_posture<>'running'))",
        (posture, stamp, session_id, stamp, stamp, posture),
    )
    return cursor.rowcount == 1


__all__ = [
    "TURN_POSTURES",
    "TURN_POSTURE_AT_COLUMN_DDL",
    "TURN_POSTURE_COLUMN_DDL",
    "accepted_hook_posture",
    "posture_timestamp",
    "stamp_turn_posture",
]
