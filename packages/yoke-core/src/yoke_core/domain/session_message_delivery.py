"""Durable hook leases, receipt expiry, and wake eligibility."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from yoke_contracts.session_control.capabilities import capability_for_surface
from yoke_core.domain import db_backend
from yoke_core.domain.session_message_types import (
    row_dict,
    timestamp,
    utc_now,
)


HOOK_LEASE_SECONDS = 30
HOOK_RESULT_CODES = frozenset(
    {
        "dropped_by_sibling_denial",
        "empty_lease",
        "injected",
        "render_output_missing",
    }
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _begin_mutation(conn: Any) -> None:
    if not db_backend.connection_is_postgres(conn) and not bool(
        getattr(conn, "in_transaction", False)
    ):
        conn.execute("BEGIN IMMEDIATE")


def _eligible_hook_event(conn: Any, session_id: str, hook_event: str) -> bool:
    row = conn.execute(
        f"SELECT executor_surface,terminated_at FROM harness_sessions WHERE session_id={_p(conn)}",
        (session_id,),
    ).fetchone()
    if row is None or row[1] is not None:
        return False
    capability = capability_for_surface(str(row[0] or ""))
    return capability is not None and hook_event in capability.inject_events


def _expire_rows(conn: Any, *, now: datetime) -> int:
    marker = _p(conn)
    stamp = timestamp(now)
    lock = " FOR UPDATE OF r" if db_backend.connection_is_postgres(conn) else ""
    leases = conn.execute(
        "SELECT r.injection_lease_id FROM session_message_recipients r "
        "JOIN session_messages m ON m.message_id=r.message_id "
        "WHERE r.state IN ('pending','injected') "
        f"AND m.expires_at<={marker}" + lock,
        (stamp,),
    ).fetchall()
    conn.execute(
        "UPDATE session_message_recipients SET state='expired', expired_at="
        + marker
        + ", injection_lease_id=NULL, injection_leased_at=NULL, "
        "injection_lease_expires_at=NULL WHERE state IN ('pending','injected') "
        "AND EXISTS (SELECT 1 FROM session_messages m "
        "WHERE m.message_id=session_message_recipients.message_id "
        f"AND m.expires_at<={marker})",
        (stamp, stamp),
    )
    for row in leases:
        if row[0]:
            conn.execute(
                "UPDATE session_message_attempts SET completed_at="
                + marker
                + ", result_code='recipient_expired' WHERE lease_id="
                + marker
                + " AND completed_at IS NULL",
                (stamp, str(row[0])),
            )
    return len(leases)


def expire_due_recipients(conn: Any, *, now: datetime | None = None) -> int:
    """Converge every due, unacknowledged receipt through one mutation."""
    _begin_mutation(conn)
    try:
        count = _expire_rows(conn, now=now or utc_now())
        conn.commit()
        return count
    except Exception:
        conn.rollback()
        raise


def _lease_candidates(
    conn: Any,
    *,
    session_id: str,
    now: datetime,
    limit: int,
) -> list[dict[str, Any]]:
    marker = _p(conn)
    stamp = timestamp(now)
    lock = (
        " FOR UPDATE OF r SKIP LOCKED"
        if db_backend.connection_is_postgres(conn)
        else ""
    )
    rows = conn.execute(
        "SELECT r.message_id,r.session_id,r.project_id,r.state,"
        "r.injection_lease_id,m.body,"
        "m.sender_actor_id,m.created_at FROM session_message_recipients r "
        "JOIN session_messages m ON m.message_id=r.message_id "
        f"WHERE r.session_id={marker} AND r.state='pending' "
        "AND m.cancelled_at IS NULL AND m.expires_at>" + marker + " "
        "AND (r.injection_lease_id IS NULL "
        "OR r.injection_lease_expires_at<=" + marker + ") "
        "ORDER BY m.created_at,r.message_id LIMIT " + marker + lock,
        (
            session_id,
            stamp,
            stamp,
            max(1, min(int(limit), 50)),
        ),
    ).fetchall()
    return [row_dict(row) for row in rows]


def _pending_receipt_count(conn: Any, *, session_id: str, now: datetime) -> int:
    marker = _p(conn)
    row = conn.execute(
        "SELECT COUNT(*) FROM session_message_recipients r "
        "JOIN session_messages m ON m.message_id=r.message_id "
        f"WHERE r.session_id={marker} AND r.state='pending' "
        f"AND m.cancelled_at IS NULL AND m.expires_at>{marker}",
        (session_id, timestamp(now)),
    ).fetchone()
    return int(row[0])


def lease_for_hook(
    conn: Any,
    *,
    session_id: str,
    hook_event: str,
    limit: int,
) -> dict[str, Any] | None:
    """Atomically lease each pending receipt for one model delivery."""
    if not _eligible_hook_event(conn, session_id, hook_event):
        return None
    current = utc_now()
    marker = _p(conn)
    lease_id = str(uuid.uuid4())
    leased: list[dict[str, Any]] = []
    _begin_mutation(conn)
    try:
        _expire_rows(conn, now=current)
        pending_count = _pending_receipt_count(conn, session_id=session_id, now=current)
        rows = _lease_candidates(
            conn,
            session_id=session_id,
            now=current,
            limit=limit,
        )
        leased_at = timestamp(current)
        lease_expires = timestamp(current + timedelta(seconds=HOOK_LEASE_SECONDS))
        for row in rows:
            old_lease = str(row.get("injection_lease_id") or "")
            if old_lease:
                conn.execute(
                    "UPDATE session_message_attempts SET completed_at="
                    + marker
                    + ",result_code='hook_lease_expired' WHERE lease_id="
                    + marker
                    + " AND completed_at IS NULL",
                    (leased_at, old_lease),
                )
            cursor = conn.execute(
                "UPDATE session_message_recipients SET injection_lease_id="
                + marker
                + ", injection_leased_at="
                + marker
                + ", injection_lease_expires_at="
                + marker
                + " WHERE message_id="
                + marker
                + " AND session_id="
                + marker
                + " AND state="
                + marker
                + " AND (injection_lease_id IS NULL "
                "OR injection_lease_expires_at<=" + marker + ")",
                (
                    lease_id,
                    leased_at,
                    lease_expires,
                    row["message_id"],
                    session_id,
                    row["state"],
                    leased_at,
                ),
            )
            if cursor.rowcount != 1:
                continue
            attempt_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO session_message_attempts "
                "(attempt_id,message_id,target_session_id,attempt_kind,"
                "adapter_revision,lease_id,started_at,evidence) VALUES ("
                + ",".join(marker for _ in range(8))
                + ")",
                (
                    attempt_id,
                    row["message_id"],
                    session_id,
                    "hook",
                    "session-message-hook-v1",
                    lease_id,
                    leased_at,
                    json.dumps({"hook_event": hook_event}, sort_keys=True),
                ),
            )
            leased.append(
                {
                    "message_id": str(row["message_id"]),
                    "body": str(row["body"]),
                    "sender_actor_id": int(row["sender_actor_id"]),
                }
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    if not leased:
        return None
    return {
        "lease_id": lease_id,
        "messages": leased,
        "remaining_count": max(0, pending_count - len(leased)),
    }


def _complete_launches(conn: Any, rows: list[dict[str, Any]], *, now: datetime) -> None:
    from yoke_core.domain.session_launch_registration import (
        complete_launch_for_message,
    )

    for row in rows:
        complete_launch_for_message(
            conn,
            message_id=str(row["message_id"]),
            session_id=str(row["target_session_id"]),
            now=timestamp(now),
            commit=False,
        )


def complete_hook_lease(
    conn: Any,
    *,
    lease_id: str,
    injected: bool,
    result: str,
) -> int:
    """Settle only the still-current recipients named by a hook lease."""
    current = utc_now()
    stamp = timestamp(current)
    marker = _p(conn)
    completed: list[dict[str, Any]] = []
    _begin_mutation(conn)
    try:
        _expire_rows(conn, now=current)
        lock = " FOR UPDATE OF r" if db_backend.connection_is_postgres(conn) else ""
        rows = conn.execute(
            "SELECT a.attempt_id,a.message_id,a.target_session_id,"
            "r.injection_lease_id,r.state FROM session_message_attempts a "
            "JOIN session_message_recipients r ON r.message_id=a.message_id "
            "AND r.session_id=a.target_session_id WHERE a.lease_id="
            + marker
            + " AND a.attempt_kind='hook' AND a.completed_at IS NULL"
            + lock,
            (lease_id,),
        ).fetchall()
        for raw in rows:
            row = row_dict(raw)
            current_lease = str(row.get("injection_lease_id") or "")
            if current_lease != lease_id:
                result_code = "stale_lease_completion"
            elif result in HOOK_RESULT_CODES:
                result_code = result
            else:
                result_code = "hook_result_unknown"
            conn.execute(
                "UPDATE session_message_attempts SET completed_at="
                + marker
                + ", result_code="
                + marker
                + " WHERE attempt_id="
                + marker,
                (stamp, result_code, row["attempt_id"]),
            )
            if current_lease != lease_id:
                continue
            if injected:
                conn.execute(
                    "UPDATE session_message_recipients SET state='injected', "
                    "injection_count=injection_count+1,last_injected_at="
                    + marker
                    + ",wake_after="
                    + marker
                    + ",injection_lease_id=NULL,injection_leased_at=NULL,"
                    "injection_lease_expires_at=NULL WHERE message_id="
                    + marker
                    + " AND session_id="
                    + marker
                    + " AND state IN ('pending','injected')",
                    (stamp, stamp, row["message_id"], row["target_session_id"]),
                )
                completed.append(row)
            else:
                conn.execute(
                    "UPDATE session_message_recipients SET injection_lease_id=NULL,"
                    "injection_leased_at=NULL,injection_lease_expires_at=NULL "
                    "WHERE message_id="
                    + marker
                    + " AND session_id="
                    + marker
                    + " AND injection_lease_id="
                    + marker,
                    (row["message_id"], row["target_session_id"], lease_id),
                )
        if injected:
            _complete_launches(conn, completed, now=current)
        conn.commit()
        return len(completed) if injected else len(rows)
    except Exception:
        conn.rollback()
        raise


__all__ = [
    "complete_hook_lease",
    "expire_due_recipients",
    "lease_for_hook",
]
