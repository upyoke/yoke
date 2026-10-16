"""Automatic-reclaim eligibility and its batched durable inputs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping

from yoke_contracts.timestamps import parse_instant
from . import db_backend
from .schema_common import _get_columns, _table_exists
from .session_cleanup_holdings import (
    active_holding_sessions,
    active_work_claim_sessions,
    effective_cleanup_ttl,
)
from .session_reclaim_activity import classify_activity
from .session_reclaim_evidence import ReclaimActivityEvidence, ReclaimClassification
from .session_reclaim_progress import newest_activity_stamp
from .sessions_analytics_core import (
    DEFAULT_PROGRESS_THRESHOLD_MINUTES,
    DEFAULT_STALE_THRESHOLD_MINUTES,
    DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES,
)

RECLAIM_SESSION_FIELDS = (
    "executor",
    "last_heartbeat",
    "last_tool_call_at",
    "ended_at",
    "terminated_at",
    "mode",
    "turn_posture",
    "tool_call_count",
    "episode_started_at",
)


def automatic_reclaim(
    row: Mapping[str, Any],
    *,
    now: datetime | None = None,
    stale_threshold_minutes: int = DEFAULT_STALE_THRESHOLD_MINUTES,
    progress_threshold_minutes: int = DEFAULT_PROGRESS_THRESHOLD_MINUTES,
    executor_ttl_overrides: Mapping[str, int] | None = None,
) -> ReclaimClassification:
    """Apply automatic protections; explicit item reclaim has separate authority."""
    ttl = effective_cleanup_ttl(
        row.get("executor"),
        base_ttl_minutes=stale_threshold_minutes,
        executor_ttl_overrides=executor_ttl_overrides,
        has_active_holdings=bool(row.get("has_active_holdings")),
        holdings_ttl_minutes=DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES,
    )

    def stamp(name: str) -> datetime | None:
        return parse_instant(row[name]) if row.get(name) is not None else None

    evidence = ReclaimActivityEvidence(
        session_id=str(row.get("session_id") or ""),
        executor=str(row.get("executor") or "unknown"),
        effective_ttl_minutes=ttl,
        last_heartbeat=stamp("last_heartbeat"),
        last_event_at=stamp("last_tool_call_at"),
        claim_last_heartbeat=None,
        claim_claimed_at=None,
        episode_started_at=stamp("episode_started_at"),
        activity_at=newest_activity_stamp(
            row.get("last_heartbeat"), row.get("last_tool_call_at")
        ),
        ended_at=stamp("ended_at") or stamp("terminated_at"),
        turn_posture=row.get("turn_posture"),
        open_tool_call_at=stamp("open_tool_call_at"),
    )
    if evidence.ended_at is not None:
        return ReclaimClassification(False, "ended", evidence)
    progress_ttl = (
        max(progress_threshold_minutes, ttl)
        if row.get("has_active_holdings")
        else progress_threshold_minutes
    )
    return classify_activity(
        evidence,
        holds_work_claim=bool(row["holds_work_claim"]),
        progress_threshold_minutes=progress_ttl if row.get("tool_call_count") else None,
        now=now,
    )


def reclaim_facts(
    conn: Any,
    rows: Iterable[Mapping[str, Any]],
    *,
    session_facts_complete: bool = False,
) -> list[dict[str, Any]]:
    """Complete roster or sweep rows in bounded reads, independent of harness.

    Session, open-call, and holdings facts have durable owners. No telemetry
    event or harness-specific interpretation participates in eligibility.
    """
    page = [dict(row) for row in rows]
    ids = tuple(dict.fromkeys(str(row["session_id"]) for row in page))
    if not ids:
        return page
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ",".join(marker for _ in ids)
    sessions = {}
    if not session_facts_complete:
        columns = _get_columns(conn, "harness_sessions")
        fields = [name for name in RECLAIM_SESSION_FIELDS if name in columns]
        sessions = {
            str(row["session_id"]): dict(row)
            for row in conn.execute(
                f"SELECT {','.join(['session_id', *fields])} FROM harness_sessions "
                f"WHERE session_id IN ({placeholders})",
                ids,
            ).fetchall()
        }
    claims = active_work_claim_sessions(conn)
    holdings = active_holding_sessions(conn)
    tools: dict[str, Any] = {}
    if _table_exists(conn, "session_tool_calls") and "completed_at" in _get_columns(
        conn, "session_tool_calls"
    ):
        tools = {
            str(row["session_id"]): row["started_at"]
            for row in conn.execute(
                "SELECT session_id, MAX(started_at) AS started_at FROM session_tool_calls "
                f"WHERE completed_at IS NULL AND session_id IN ({placeholders}) GROUP BY session_id",
                ids,
            ).fetchall()
        }
    for row in page:
        sid = str(row["session_id"])
        facts = sessions.get(sid, {})
        for name in RECLAIM_SESSION_FIELDS:
            if name in facts:
                row[name] = facts[name]
        row["holds_work_claim"] = sid in claims
        row["has_active_holdings"] = sid in holdings
        row["open_tool_call_at"] = tools.get(sid)
    return page
