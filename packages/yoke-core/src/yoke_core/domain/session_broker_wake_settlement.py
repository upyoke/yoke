"""Settle peer-hook reservations and hand them to one native relay run."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.session_broker_wake import (
    BROKER_HOOK_LEASE_SECONDS,
    BROKER_JOB_TIMEOUT_SECONDS,
)
from yoke_core.domain.session_message_types import (
    parse_timestamp,
    row_dict,
    timestamp,
    utc_now,
)
from yoke_core.domain.session_relay_evidence import redacted_evidence
from yoke_core.domain.session_relay_storage import marker


def _lock(conn: Any, alias: str, *, skip: bool = False) -> str:
    if not db_backend.connection_is_postgres(conn):
        return ""
    return f" FOR UPDATE OF {alias}" + (" SKIP LOCKED" if skip else "")


def _begin(conn: Any) -> None:
    if not db_backend.connection_is_postgres(conn) and not bool(
        getattr(conn, "in_transaction", False)
    ):
        conn.execute("BEGIN IMMEDIATE")


def close_broker_attempt(
    conn: Any, *, attempt_id: str, result_code: str, now: str
) -> bool:
    p = marker(conn)
    cursor = conn.execute(
        "UPDATE session_message_attempts SET completed_at="
        + p
        + ",result_code="
        + p
        + ",evidence="
        + p
        + f" WHERE attempt_id={p} AND completed_at IS NULL",
        (
            now,
            result_code,
            redacted_evidence({"result_code": result_code}),
            attempt_id,
        ),
    )
    return cursor.rowcount == 1


def complete_broker_hook_lease(
    conn: Any,
    *,
    lease_id: str,
    delivered: bool,
    result: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Record whether the broker instruction survived aggregate rendering."""
    current = timestamp(now or utc_now())
    p = marker(conn)
    _begin(conn)
    try:
        row = conn.execute(
            "SELECT attempt_id,result_code,completed_at FROM session_message_attempts a "
            f"WHERE lease_id={p} AND attempt_kind='wake_broker'" + _lock(conn, "a"),
            (lease_id,),
        ).fetchone()
        if row is None:
            conn.rollback()
            return {"lease_id": lease_id, "result_code": "broker_attempt_missing"}
        attempt_id = str(row[0])
        prior = str(row[1] or "")
        if row[2] is not None or prior == "broker_instructed":
            conn.commit()
            return {"attempt_id": attempt_id, "result_code": prior}
        if prior != "broker_hook_leased":
            conn.rollback()
            return {"attempt_id": attempt_id, "result_code": "broker_lease_stale"}
        if delivered:
            result_code = "broker_instructed"
            conn.execute(
                "UPDATE session_message_attempts SET result_code="
                + p
                + ",evidence="
                + p
                + f" WHERE attempt_id={p} AND completed_at IS NULL",
                (
                    result_code,
                    redacted_evidence({"result_code": result_code}),
                    attempt_id,
                ),
            )
        else:
            result_code = (
                "broker_render_dropped"
                if result == "dropped_by_sibling_denial"
                else "broker_render_missing"
            )
            close_broker_attempt(
                conn, attempt_id=attempt_id, result_code=result_code, now=current
            )
        conn.commit()
        return {"attempt_id": attempt_id, "result_code": result_code}
    except Exception:
        conn.rollback()
        raise


def _after(value: Any, boundary: datetime) -> bool:
    parsed = parse_timestamp(value)
    return bool(parsed and parsed > boundary)


def settle_broker_wake_losses(conn: Any, *, now: datetime | None = None) -> int:
    """Close abandoned peer reservations without guessing native outcomes."""
    current = now or utc_now()
    current_text = timestamp(current)
    _begin(conn)
    try:
        rows = conn.execute(
            "SELECT a.attempt_id,a.result_code,a.started_at,"
            "b.machine_id AS broker_machine,b.ended_at AS broker_ended,"
            "b.turn_posture AS broker_posture,t.machine_id AS target_machine,"
            "t.last_tool_call_at,t.turn_posture_at,r.machine_id AS routed_machine,"
            "r.state,r.injection_lease_id,r.last_injected_at,m.cancelled_at,m.expires_at "
            "FROM session_message_attempts a "
            "LEFT JOIN harness_sessions b ON b.session_id=a.broker_session_id "
            "LEFT JOIN harness_sessions t ON t.session_id=a.target_session_id "
            "LEFT JOIN session_message_recipients r ON r.message_id=a.message_id "
            "AND r.session_id=a.target_session_id "
            "LEFT JOIN session_messages m ON m.message_id=a.message_id "
            "WHERE a.attempt_kind='wake_broker' AND a.completed_at IS NULL "
            "AND a.result_code IN ('broker_hook_leased','broker_instructed') "
            "ORDER BY a.started_at,a.attempt_id" + _lock(conn, "a", skip=True)
        ).fetchall()
        changed = 0
        for raw in rows:
            row = row_dict(raw)
            started = parse_timestamp(row.get("started_at"))
            if started is None:
                code = "broker_state_invalid"
            elif (
                row.get("state") not in {"pending", "injected"}
                or row.get("cancelled_at") is not None
                or not parse_timestamp(row.get("expires_at"))
                or parse_timestamp(row.get("expires_at")) <= current
                or row.get("target_machine") != row.get("routed_machine")
                or row.get("injection_lease_id") is not None
                or _after(row.get("last_injected_at"), started)
                or _after(row.get("last_tool_call_at"), started)
                or _after(row.get("turn_posture_at"), started)
            ):
                code = "broker_target_changed"
            elif (
                row.get("result_code") == "broker_hook_leased"
                and started + timedelta(seconds=BROKER_HOOK_LEASE_SECONDS) <= current
            ):
                code = "broker_hook_lease_expired"
            elif row.get("result_code") == "broker_instructed" and (
                started + timedelta(seconds=BROKER_HOOK_LEASE_SECONDS) <= current
                and (
                    not row.get("broker_machine")
                    or row.get("broker_machine") != row.get("target_machine")
                    or row.get("broker_ended") is not None
                    or row.get("broker_posture") == "waiting"
                )
            ):
                code = "broker_lost"
            elif (
                row.get("result_code") == "broker_instructed"
                and started + timedelta(seconds=BROKER_JOB_TIMEOUT_SECONDS) <= current
            ):
                code = "broker_timeout"
            else:
                continue
            changed += int(
                close_broker_attempt(
                    conn,
                    attempt_id=str(row["attempt_id"]),
                    result_code=code,
                    now=current_text,
                )
            )
        conn.commit()
        return changed
    except Exception:
        conn.rollback()
        raise


__all__ = [
    "close_broker_attempt",
    "complete_broker_hook_lease",
    "settle_broker_wake_losses",
]
