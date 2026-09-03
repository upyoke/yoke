"""Durable machine evidence about a session's most recently known process.

The relay can prove that a process it recorded is gone.  That fact is not a
session-end decision when the session still holds authority, but it must stay
visible until later activity proves a replacement process has taken over.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping

from yoke_core.domain.session_message_types import (
    parse_timestamp,
    timestamp,
    utc_now,
)


NATIVE_PROCESS_GONE_AT_COLUMN = "native_process_gone_at"
NATIVE_PROCESS_GONE_EVIDENCE_COLUMN = "native_process_gone_evidence"
NATIVE_PROCESS_OBSERVATION_COLUMN_DDL = "TEXT DEFAULT NULL"
NATIVE_PROCESS_GONE_STATE = "gone"
CLAIMS_HELD_STATUS = "claims_held"


def _decoded_evidence(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        decoded = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(decoded) if isinstance(decoded, Mapping) else {}


def record_native_process_gone(
    conn: Any,
    session_id: str,
    evidence: Mapping[str, Any],
    *,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Record a relay's verified-dead process evidence without committing."""
    stamp = timestamp(observed_at or utc_now())
    payload = json.dumps(dict(evidence), sort_keys=True, separators=(",", ":"))
    conn.execute(
        f"UPDATE harness_sessions SET {NATIVE_PROCESS_GONE_AT_COLUMN}=%s, "
        f"{NATIVE_PROCESS_GONE_EVIDENCE_COLUMN}=%s WHERE session_id=%s",
        (stamp, payload, session_id),
    )
    return {
        "state": NATIVE_PROCESS_GONE_STATE,
        "observed_at": stamp,
        "evidence": dict(evidence),
    }


def current_native_process_observation(
    row: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return process-gone evidence unless later activity superseded it."""
    observed = parse_timestamp(row.get(NATIVE_PROCESS_GONE_AT_COLUMN))
    if observed is None:
        return None
    activity = [
        parsed
        for field in ("last_heartbeat", "last_tool_call_at", "episode_started_at")
        if (parsed := parse_timestamp(row.get(field))) is not None
    ]
    # Timestamps have second precision. Equal stamps can be the report and
    # the episode that just died; only strictly later activity proves a
    # replacement process or subsequent tool call.
    if activity and max(activity) > observed:
        return None
    return {
        "state": NATIVE_PROCESS_GONE_STATE,
        "observed_at": str(row.get(NATIVE_PROCESS_GONE_AT_COLUMN) or ""),
        "evidence": _decoded_evidence(row.get(NATIVE_PROCESS_GONE_EVIDENCE_COLUMN)),
    }


__all__ = [
    "CLAIMS_HELD_STATUS",
    "NATIVE_PROCESS_GONE_AT_COLUMN",
    "NATIVE_PROCESS_GONE_EVIDENCE_COLUMN",
    "NATIVE_PROCESS_GONE_STATE",
    "NATIVE_PROCESS_OBSERVATION_COLUMN_DDL",
    "current_native_process_observation",
    "record_native_process_gone",
]
