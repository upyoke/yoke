"""Posture- and idle-keyed wake eligibility for durable message receipts."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.session_message_authorization import project_policy
from yoke_core.domain.session_message_delivery import (
    _begin_mutation,
    _expire_rows,
)
from yoke_core.domain.session_message_routing import (
    latest_hook_activity,
    session_liveness,
)
from yoke_core.domain.session_message_types import (
    parse_timestamp,
    row_dict,
    timestamp,
    utc_now,
)
from yoke_core.domain.session_relay_types import WakeMode


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def wake_eligible_recipients(
    conn: Any,
    *,
    now: datetime | None = None,
    bypass_waiting_retry_cooldown: bool = False,
    ignore_attempt_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return redacted wake routes with their scheduler authority."""
    from yoke_core.hooks.session_message_delivery import wake_eligible

    current = now or utc_now()
    marker = _p(conn)
    open_attempt_filter = ""
    open_attempt_params: tuple[Any, ...] = ()
    if ignore_attempt_id:
        open_attempt_filter = f"AND a.attempt_id<>{marker} "
        open_attempt_params = (ignore_attempt_id,)
    _begin_mutation(conn)
    try:
        _expire_rows(conn, now=current)
        rows = conn.execute(
            "SELECT r.*,m.created_at AS message_created_at,m.expires_at,"
            "hs.executor,hs.execution_lane,hs.last_heartbeat,"
            "hs.last_tool_call_at,hs.ended_at,hs.turn_posture,"
            "hs.turn_posture_at "
            "FROM session_message_recipients r "
            "JOIN session_messages m ON m.message_id=r.message_id "
            "JOIN harness_sessions hs ON hs.session_id=r.session_id "
            "WHERE r.state IN ('pending','injected') AND m.cancelled_at IS NULL "
            "AND (r.wake_after<="
            + marker
            + " OR (r.state='pending' AND hs.turn_posture='waiting' "
            "AND r.injection_lease_id IS NULL)) AND m.expires_at>"
            + marker
            + " AND (r.injection_lease_id IS NULL OR ("
            "r.injection_lease_expires_at IS NOT NULL "
            "AND r.injection_lease_expires_at<="
            + marker
            + ")) AND NOT EXISTS (SELECT 1 FROM session_message_attempts a "
            "WHERE a.message_id=r.message_id "
            "AND a.target_session_id=r.session_id "
            "AND a.attempt_kind IN ('wake_relay','wake_broker') "
            "AND a.completed_at IS NULL "
            + open_attempt_filter
            + ")"
            + " ORDER BY r.wake_after,r.message_id,r.session_id",
            (
                timestamp(current),
                timestamp(current),
                timestamp(current),
                *open_attempt_params,
            ),
        ).fetchall()
        eligible: list[dict[str, Any]] = []
        for raw in rows:
            row = row_dict(raw)
            policy = project_policy(conn, int(row["project_id"]))
            liveness = session_liveness(row, now=current)
            if int(row["wake_attempt_count"] or 0) >= policy.max_wake_attempts:
                continue
            # Delivery can repeat, but a live prompt must never receive a wake.
            if row["state"] == "injected" and (
                liveness == "active" or not policy.reinject_until_acknowledged
            ):
                continue
            created_at = parse_timestamp(row["message_created_at"])
            wake_after = parse_timestamp(row["wake_after"])
            if created_at is None or wake_after is None:
                continue
            activity = latest_hook_activity(row)
            if activity is not None and activity <= created_at:
                activity = None
            waiting_pending = (
                row["state"] == "pending" and row.get("turn_posture") == "waiting"
            )
            idle_window = timedelta(minutes=policy.wake_after_idle_minutes)
            if waiting_pending:
                if row.get("injection_lease_id") is not None:
                    continue
                previous_wake = parse_timestamp(row.get("last_wake_at"))
                if (
                    not bypass_waiting_retry_cooldown
                    and int(row["wake_attempt_count"] or 0) > 0
                    and (previous_wake is None or previous_wake + idle_window > current)
                ):
                    continue
                wake_mode = WakeMode.WAITING
            else:
                if not wake_eligible(
                    recipient_state=str(row["state"]),
                    liveness=liveness,
                    recipient_created_at=created_at,
                    wake_after=wake_after,
                    last_hook_activity_at=activity,
                    idle_window=idle_window,
                    now=current,
                ):
                    continue
                wake_mode = WakeMode.IDLE_TIMEOUT
            eligible.append(
                {
                    "message_id": str(row["message_id"]),
                    "session_id": str(row["session_id"]),
                    "project_id": int(row["project_id"]),
                    "machine_id": row["machine_id"],
                    "executor_surface": row["executor_surface"],
                    "executor_version": row["executor_version"],
                    "state": str(row["state"]),
                    "wake_mode": wake_mode.value,
                    "liveness": liveness,
                    "turn_posture": str(row["turn_posture"]),
                    "turn_posture_at": row["turn_posture_at"],
                    "injection_lease_id": row["injection_lease_id"],
                    "injection_lease_expires_at": row["injection_lease_expires_at"],
                    "wake_attempt_count": int(row["wake_attempt_count"] or 0),
                    "last_wake_at": row["last_wake_at"],
                }
            )
        conn.commit()
        return eligible
    except Exception:
        conn.rollback()
        raise


__all__ = ["wake_eligible_recipients"]
