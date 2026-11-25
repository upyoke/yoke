"""Automatic-reclaim eligibility and its batched durable inputs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from yoke_contracts.timestamps import parse_instant
from . import db_backend
from .db_optional_queries import fetch_optional_rows
from .schema_common import _get_columns, _table_exists
from .session_cleanup_holdings import (
    active_holding_sessions,
    active_work_claim_sessions,
    effective_cleanup_ttl,
)
from .session_keepalive import session_keepalive_holds
from .session_reclaim_activity import (
    REASON_KEEPALIVE_HELD,
    REASON_WAKE_DELIVERY_IN_FLIGHT,
    classify_activity,
)
from .session_reclaim_evidence import ReclaimActivityEvidence, ReclaimClassification
from .session_reclaim_progress import newest_activity_stamp, tool_activity_stamp
from .sessions_analytics_core import (
    DEFAULT_PROGRESS_THRESHOLD_MINUTES,
    DEFAULT_STALE_THRESHOLD_MINUTES,
    DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES,
)

RECLAIM_SESSION_FIELDS = (
    "executor",
    "project_id",
    "native_process_gone_at",
    "native_process_gone_evidence",
    "turn_posture_at",
    "native_turn_end_recorded_at",
    "quiet_reason",
    "last_heartbeat",
    "last_tool_call_at",
    "last_child_tool_call_at",
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
        last_event_at=tool_activity_stamp(row),
        claim_last_heartbeat=None,
        claim_claimed_at=None,
        episode_started_at=stamp("episode_started_at"),
        activity_at=newest_activity_stamp(
            row.get("last_heartbeat"), tool_activity_stamp(row)
        ),
        ended_at=stamp("ended_at") or stamp("terminated_at"),
        turn_posture=row.get("turn_posture"),
        open_tool_call_at=stamp("open_tool_call_at"),
        session_facts=row,
    )
    if evidence.ended_at is None:
        if row.get("keepalive"):
            return ReclaimClassification(False, REASON_KEEPALIVE_HELD, evidence)
        if row.get("wake_delivery") or row.get("open_wake_attempt"):
            return ReclaimClassification(
                False, REASON_WAKE_DELIVERY_IN_FLIGHT, evidence
            )
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


def _reclaim_delivery_facts(
    conn: Any, ids: Sequence[str]
) -> dict[str, dict[str, bool]]:
    """Read the same delivery guards for a whole sweep, roster, or locked row."""
    from .sessions_render_end_if_empty import wake_deliveries_in_flight

    if not ids:
        return {}
    keepalives = session_keepalive_holds(conn, ids)
    deliveries = wake_deliveries_in_flight(conn, ids)
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ",".join(marker for _ in ids)
    attempts = {
        str(row["target_session_id"])
        for row in fetch_optional_rows(
            conn,
            "SELECT DISTINCT target_session_id FROM session_message_attempts "
            "WHERE completed_at IS NULL AND attempt_kind IN ('wake_relay','wake_broker') "
            f"AND target_session_id IN ({placeholders})",
            ids,
            savepoint="_yoke_reclaim_open_wake_attempts",
        )
    }
    return {
        sid: {
            "keepalive": sid in keepalives,
            "wake_delivery": sid in deliveries,
            "open_wake_attempt": sid in attempts,
        }
        for sid in ids
    }


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
    delivery = _reclaim_delivery_facts(conn, ids)
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
    from yoke_contracts.project_contract.project_keys import (
        DEFAULT_SESSION_IDLE_MINUTES,
    )
    from .project_policy_capabilities import project_policy_value

    project_ids = {
        row.get(
            "project_id", sessions.get(str(row["session_id"]), {}).get("project_id")
        )
        for row in page
    }
    idle_minutes = {
        project_id: project_policy_value(
            conn, project_id, "session_idle_minutes", DEFAULT_SESSION_IDLE_MINUTES
        )
        for project_id in project_ids
        if project_id is not None and _table_exists(conn, "project_capabilities")
    }
    for row in page:
        sid = str(row["session_id"])
        facts = sessions.get(sid, {})
        for name in RECLAIM_SESSION_FIELDS:
            if name in facts and (name != "project_id" or name not in row):
                row[name] = facts[name]
        row["session_idle_minutes"] = idle_minutes.get(
            row.get("project_id"), DEFAULT_SESSION_IDLE_MINUTES
        )
        row.update(delivery[sid])
        row["holds_work_claim"] = sid in claims
        row["has_active_holdings"] = sid in holdings
        row["open_tool_call_at"] = tools.get(sid)
    return page
