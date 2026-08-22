"""Converge expired relay leases without guessing native outcomes."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.session_relay_evidence import (
    redacted_evidence,
    redacted_evidence_document,
)
from yoke_core.domain.session_relay_storage import (
    clear_relay_job,
    marker,
)


_LEASE_EXPIRED_CODE = "relay_lease_expired"


def settle_expired_relay_leases(conn: Any, *, now: str) -> int:
    """Close stale attempts and clear their relay-local ownership marker."""
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
    for relay_id, lease_id in rows:
        lease = str(lease_id)
        wake = conn.execute(
            "SELECT attempt_id FROM session_message_attempts "
            f"WHERE lease_id={p} AND attempt_kind='wake_relay' "
            "AND completed_at IS NULL LIMIT 1",
            (lease,),
        ).fetchone()
        if wake is not None:
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
            changed += 1
        launch = conn.execute(
            "SELECT launch_id FROM session_launch_attempts "
            f"WHERE lease_id={p} AND completed_at IS NULL LIMIT 1",
            (lease,),
        ).fetchone()
        if launch is not None:
            from yoke_core.domain.session_launch_execution import (
                report_launch_attempt,
            )

            report_launch_attempt(
                conn,
                launch_id=str(launch[0]),
                lease_id=lease,
                result_code="outcome_unknown",
                evidence=redacted_evidence_document(
                    {"result_code": _LEASE_EXPIRED_CODE}
                ),
                now=now,
            )
            changed += 1
        clear_relay_job(conn, relay_id=str(relay_id), lease_id=lease)
    conn.commit()
    return changed


__all__ = ["settle_expired_relay_leases"]
