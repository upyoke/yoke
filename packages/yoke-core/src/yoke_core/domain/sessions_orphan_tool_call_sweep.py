"""Sentinel sweep for orphaned tool calls at session end.

When a session ends — via the destructive-end path or the idle-auto-end
path — any tool call that started but never completed makes the activity
state lie ("still running" is indistinguishable from "died silently").
The source of truth for "orphan" is the ``session_tool_calls`` rolling
table: open rows (``completed_at IS NULL``) for the ending session.

The sweep maintains BOTH surfaces (operator-locked R3 decision):

* it closes each open ``session_tool_calls`` row in place
  (``completed_at`` = sweep time, ``outcome='interrupted'``) — the state
  every reader consumes; and
* it still synthesizes a sentinel ``HarnessToolCallCompleted`` event row
  with ``event_outcome=OUTCOME_INTERRUPTED`` and a structured reason
  payload, keeping the telemetry ledger's duration/outcome statistics
  honest. Readers never consume these events as state.

Idempotency: the second pass sees no open rows (pass one closed them)
and emits nothing. The events table additionally enforces sentinel
dedup structurally via ``idx_events_tool_use_id_dedup ON
events(tool_use_id, event_name)``.

The module is a pure helper: callers pass an open connection so the
row closes and sentinel inserts share the session-end transaction.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List

from yoke_core.domain.events_project_identity import (
    resolve_envelope_project_id_for_event,
)
from yoke_core.domain.events_tool_call_outcome import OUTCOME_INTERRUPTED
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.session_activity_state import COMPLETION_EVENT_NAMES

# Approved lifecycle_reason values for the structured sentinel payload.
LIFECYCLE_REASONS: frozenset[str] = frozenset(
    {
        "session_end_destructive",
        "stop_hook_destructive",
        "session_idle_auto_ended",
    }
)

__all__ = [
    "LIFECYCLE_REASONS",
    "COMPLETION_EVENT_NAMES",
    "OrphanSweepReason",
    "build_sentinel_reason",
    "sweep_orphaned_tool_calls",
]


@dataclass(frozen=True)
class OrphanSweepReason:
    """Structured reason payload written to ``envelope.context.detail.sentinel_reason``.

    Four named fields so audit queries can filter without grepping prose.
    """

    ending_session_id: str
    sentinel_emitted_at: str
    original_started_at: str
    lifecycle_reason: str

    def as_dict(self) -> Dict[str, str]:
        return asdict(self)


def _iso_now() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def build_sentinel_reason(
    open_row: Any,
    ending_session_id: str,
    lifecycle_reason: str,
) -> OrphanSweepReason:
    """Construct the structured sentinel reason payload from an open row."""
    return OrphanSweepReason(
        ending_session_id=ending_session_id,
        sentinel_emitted_at=_iso_now(),
        original_started_at=open_row["started_at"] or "",
        lifecycle_reason=lifecycle_reason,
    )


def _find_open_tool_calls(conn: Any, session_id: str) -> List[Any]:
    """Return the open ``session_tool_calls`` rows for ``session_id``."""
    return list(
        conn.execute(
            "SELECT id, session_id, tool_use_id, tool_name, started_at "
            "FROM session_tool_calls "
            "WHERE session_id = %s AND completed_at IS NULL "
            "ORDER BY started_at ASC",
            (session_id,),
        )
    )


def _build_sentinel_envelope(
    open_row: Any,
    session_id: str,
    reason: OrphanSweepReason,
    event_time: str,
    event_id: str,
) -> Dict[str, Any]:
    """Construct the sentinel envelope dict for one orphaned tool call."""
    tool_name = open_row["tool_name"]

    detail: Dict[str, Any] = {
        "tool_name": tool_name,
        "sentinel_reason": reason.as_dict(),
    }

    envelope: Dict[str, Any] = {
        "event_id": event_id,
        "event_name": "HarnessToolCallCompleted",
        "event_kind": "system",
        "event_type": "tool_call",
        "event_time": event_time,
        "event_outcome": OUTCOME_INTERRUPTED,
        "source_type": "agent",
        "severity": "WARN",
        "session_id": session_id,
        "service": "cli",
        "project": "yoke",
        "item_id": None,
        "task_num": None,
        "agent": None,
        "tool_name": tool_name,
        "duration_ms": None,
        "exit_code": None,
        "trace_id": None,
        "parent_id": None,
        "anomaly_flags": "interrupted",
        "tool_use_id": open_row["tool_use_id"],
        "turn_id": None,
        "hook_event_name": None,
        "context": {"detail": detail},
    }
    return envelope


def _insert_sentinel(conn: Any, envelope: Dict[str, Any]) -> bool:
    """Insert the sentinel row. Returns True on insert, False on dedup skip."""
    envelope_json = json.dumps(envelope, separators=(",", ":"))
    project_id = resolve_envelope_project_id_for_event(conn, None, envelope)
    values = (
        envelope["event_id"],
        envelope["source_type"],
        envelope["session_id"],
        envelope["severity"],
        envelope["event_kind"],
        envelope["event_type"],
        envelope["event_name"],
        envelope["event_outcome"],
        envelope["service"],
        project_id,
        envelope["item_id"],
        envelope["task_num"],
        envelope["agent"],
        envelope["tool_name"],
        envelope["duration_ms"],
        envelope["exit_code"],
        envelope["anomaly_flags"],
        envelope["tool_use_id"],
        envelope["turn_id"],
        envelope["hook_event_name"],
        envelope_json,
        envelope["event_time"],
    )
    cursor = conn.execute(
        """INSERT INTO events (
            event_id, source_type, session_id, severity,
            event_kind, event_type, event_name, event_outcome,
            service, project_id, item_id, task_num,
            agent, tool_name, duration_ms, exit_code,
            anomaly_flags, tool_use_id, turn_id,
            hook_event_name, envelope, created_at
        ) VALUES (
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s
        )
        ON CONFLICT(event_id) DO NOTHING""",
        values,
    )
    return cursor.rowcount > 0


def sweep_orphaned_tool_calls(
    conn: Any,
    *,
    session_id: str,
    lifecycle_reason: str,
) -> Dict[str, Any]:
    """Close open tool-call rows and emit sentinel completion events.

    Args:
        conn: Open read-write connection. The caller owns the transaction
            so the row closes and sentinel inserts share the session-end
            commit.
        session_id: The session that is ending.
        lifecycle_reason: One of :data:`LIFECYCLE_REASONS`.

    Returns:
        Diagnostic dict with:
          - ``sentinel_event_ids``: list of new sentinel event ids.
          - ``skipped_null_tool_use_id``: retained for interface
            stability; structurally 0 — ``session_tool_calls`` rows
            always carry a ``tool_use_id`` (the observe pre-hook drops
            payloads without one before any row exists).
          - ``matched``: count of orphan rows closed.

    The sweep does NOT bump ``last_tool_call_at`` / ``tool_call_count``
    — sweep time is not agent activity, and the ending session's
    ``ended_at`` dominates every liveness classification anyway.
    """
    if lifecycle_reason not in LIFECYCLE_REASONS:
        raise ValueError(
            f"lifecycle_reason must be one of {sorted(LIFECYCLE_REASONS)}; "
            f"got {lifecycle_reason!r}"
        )

    # No-op when the state table is absent (test isolation surfaces).
    if not _table_exists(conn, "session_tool_calls"):
        return {
            "sentinel_event_ids": [],
            "skipped_null_tool_use_id": 0,
            "matched": 0,
        }

    orphans = _find_open_tool_calls(conn, session_id)
    events_present = _table_exists(conn, "events")

    sentinel_event_ids: List[str] = []
    matched = 0
    for row in orphans:
        reason = build_sentinel_reason(row, session_id, lifecycle_reason)
        event_time = reason.sentinel_emitted_at
        conn.execute(
            "UPDATE session_tool_calls "
            "SET completed_at = %s, outcome = %s "
            "WHERE id = %s AND completed_at IS NULL",
            (event_time, OUTCOME_INTERRUPTED, row["id"]),
        )
        matched += 1
        if not events_present:
            continue
        event_id = str(uuid.uuid4())
        envelope = _build_sentinel_envelope(
            row, session_id, reason, event_time, event_id
        )
        if _insert_sentinel(conn, envelope):
            sentinel_event_ids.append(event_id)

    return {
        "sentinel_event_ids": sentinel_event_ids,
        "skipped_null_tool_use_id": 0,
        "matched": matched,
    }
