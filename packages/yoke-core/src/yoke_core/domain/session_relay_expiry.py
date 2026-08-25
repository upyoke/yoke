"""Converge expired relay leases without guessing native outcomes."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.session_relay_evidence import (
    redacted_evidence,
    redacted_evidence_document,
)
from yoke_core.domain.session_relay_storage import (
    clear_relay_batch_when_drained,
    marker,
)


_LEASE_EXPIRED_CODE = "relay_lease_expired"


def settle_expired_relay_leases(conn: Any, *, now: str) -> int:
    """Close every job stranded by an expired batch without guessing outcomes."""
    from yoke_core.domain.session_launch_deadlines import settle_launch_deadlines

    settle_launch_deadlines(conn, now=now)
    p = marker(conn)
    rows = conn.execute(
        "SELECT relay_id,lease_id FROM session_relays "
        f"WHERE lease_id IS NOT NULL AND lease_expires_at<={p} "
        "ORDER BY relay_id",
        (now,),
    ).fetchall()
    changed = 0
    for relay_id, batch_id in rows:
        changed += _settle_wake(conn, str(batch_id), now=now)
        changed += _settle_launches(conn, str(batch_id), now=now)
        clear_relay_batch_when_drained(
            conn,
            relay_id=str(relay_id),
            batch_id=str(batch_id),
        )
    conn.commit()
    return changed


def _settle_wake(conn: Any, batch_id: str, *, now: str) -> int:
    """Close the single wake a batch marker owns, when it owns one."""
    p = marker(conn)
    wake = conn.execute(
        "SELECT attempt_id FROM session_message_attempts "
        f"WHERE lease_id={p} AND attempt_kind IN ('wake_relay','wake_broker') "
        "AND completed_at IS NULL LIMIT 1",
        (batch_id,),
    ).fetchone()
    if wake is None:
        return 0
    conn.execute(
        "UPDATE session_message_attempts SET completed_at=" + p + ","
        "result_code=" + p + ",evidence=" + p + f" WHERE attempt_id={p}",
        (
            now,
            _LEASE_EXPIRED_CODE,
            redacted_evidence({"result_code": _LEASE_EXPIRED_CODE}),
            wake[0],
        ),
    )
    return 1


def _settle_launches(conn: Any, batch_id: str, *, now: str) -> int:
    """Reconcile every launch this batch leased but never reported."""
    from yoke_core.domain.session_launch_execution import report_launch_attempt

    p = marker(conn)
    stranded = conn.execute(
        "SELECT launch_id,lease_id FROM session_launch_attempts "
        f"WHERE batch_id={p} AND completed_at IS NULL "
        "ORDER BY started_at,launch_id",
        (batch_id,),
    ).fetchall()
    for launch_id, lease_id in stranded:
        report_launch_attempt(
            conn,
            launch_id=str(launch_id),
            lease_id=str(lease_id),
            result_code="outcome_unknown",
            evidence=redacted_evidence_document({"result_code": _LEASE_EXPIRED_CODE}),
            now=now,
        )
    return len(stranded)


__all__ = ["settle_expired_relay_leases"]
