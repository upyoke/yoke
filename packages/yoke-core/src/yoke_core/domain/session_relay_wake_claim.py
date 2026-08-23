"""Atomic per-recipient claims for native wake attempts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from uuid import uuid4

from yoke_core.domain.session_relay_evidence import redacted_evidence
from yoke_core.domain.session_relay_storage import marker, shifted
from yoke_core.domain.session_relay_types import WAKE_LEASE_SECONDS


@dataclass(frozen=True)
class WakeAttemptClaim:
    attempt_id: str
    lease_id: str
    lease_expires_at: str


def claim_wake_attempt(
    conn: Any,
    *,
    candidate: Mapping[str, Any],
    now: str,
) -> WakeAttemptClaim | None:
    """CAS one eligible receipt and open its native wake attempt.

    The expected attempt count and last-wake stamp come from eligibility
    selection. Concurrent relays that selected the same row cannot both update
    that version, and an incomplete native attempt is a second defensive gate.
    """
    message_id = str(candidate["message_id"])
    session_id = str(candidate["session_id"])
    expected_count = int(candidate.get("wake_attempt_count") or 0)
    expected_last = candidate.get("last_wake_at")
    attempt_id = str(uuid4())
    lease_id = str(uuid4())
    lease_expires_at = shifted(now, seconds=WAKE_LEASE_SECONDS)
    p = marker(conn)
    last_clause = "last_wake_at IS NULL"
    params: list[Any] = [now, message_id, session_id, expected_count]
    if expected_last is not None:
        last_clause = f"last_wake_at={p}"
        params.append(expected_last)
    updated = conn.execute(
        "UPDATE session_message_recipients SET wake_attempt_count="
        "wake_attempt_count+1,last_wake_at="
        + p
        + f" WHERE message_id={p} AND session_id={p} AND state='pending' "
        + f"AND wake_attempt_count={p} AND {last_clause} "
        "AND NOT EXISTS (SELECT 1 FROM session_message_attempts a "
        "WHERE a.message_id=session_message_recipients.message_id "
        "AND a.target_session_id=session_message_recipients.session_id "
        "AND a.attempt_kind IN ('wake_relay','wake_broker') "
        "AND a.completed_at IS NULL)",
        tuple(params),
    )
    if updated.rowcount != 1:
        conn.rollback()
        return None
    conn.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id,message_id,target_session_id,attempt_kind,lease_id,"
        "started_at,evidence) "
        f"VALUES ({','.join(p for _ in range(7))})",
        (
            attempt_id,
            message_id,
            session_id,
            "wake_relay",
            lease_id,
            now,
            redacted_evidence(None),
        ),
    )
    return WakeAttemptClaim(
        attempt_id=attempt_id,
        lease_id=lease_id,
        lease_expires_at=lease_expires_at,
    )


__all__ = ["WakeAttemptClaim", "claim_wake_attempt"]
