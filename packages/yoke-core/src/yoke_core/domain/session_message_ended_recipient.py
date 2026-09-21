"""Stop recruiting a successor for mail addressed to an ended session.

A pending envelope whose recipient has ended cannot be acknowledged by any
other session (``acknowledge_self_only``), so spawning a new native to take
delivery cannot settle it. Each spawn costs a session, a stuck turn, and
relay capacity, and none of them can change the outcome.

Quiet, stale, parked, and waiting recipients keep the routes they have
today. This gate is specifically ``ended_at`` (or a kill) on a session that
has not declared a remaining wait. The envelope stays pending; the named
recovery is for the sender or seat to cancel it, never an automatic ack.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from yoke_core.domain.session_mode import session_is_parked
from yoke_core.domain.session_message_types import timestamp
from yoke_core.domain.session_relay_evidence import redacted_evidence
from yoke_core.domain.session_relay_storage import marker


RECIPIENT_ENDED_RESULT = "recipient_ended"
RECIPIENT_TERMINATED_RESULT = "recipient_terminated"
CANCEL_RECOVERY = "yoke messages cancel {message_id}"
_ADAPTER_REVISION = "session-ended-recipient-v1"


def cancel_recovery(message_id: str | None = None) -> str:
    """The named settle command for mail that can no longer be delivered."""
    return CANCEL_RECOVERY.format(message_id=message_id or "MESSAGE-ID")


def recipient_has_no_delivery_route(row: Mapping[str, Any]) -> bool:
    """True when the addressed session is gone and has no remaining wake route.

    A parked or waiting session still asked to be resumed; those stay
    eligible. A kill or an ordinary end with neither declaration does not.
    """
    if row.get("terminated_at"):
        return True
    if not row.get("ended_at"):
        return False
    if session_is_parked(row.get("mode")):
        return False
    return str(row.get("turn_posture") or "") != "waiting"


def skip_ended_recipient(
    conn: Any,
    row: Mapping[str, Any],
    *,
    now: datetime,
) -> bool:
    """Record why this receipt is undeliverable and take it off the wake queue.

    One attempt row per receipt, so a poll loop cannot manufacture a new
    native each time. The message is not cancelled: that would discard an
    unread report.
    """
    if not recipient_has_no_delivery_route(row):
        return False
    result = (
        RECIPIENT_TERMINATED_RESULT
        if row.get("terminated_at")
        else RECIPIENT_ENDED_RESULT
    )
    _record(conn, row, result_code=result, now=now)
    return True


def _record(
    conn: Any,
    row: Mapping[str, Any],
    *,
    result_code: str,
    now: datetime,
) -> None:
    message_id = str(row["message_id"])
    session_id = str(row["session_id"])
    evidence = {
        "result_code": result_code,
        "skip_reason": f"recipient_session_ended; {cancel_recovery(message_id)}",
        "turn_posture": str(row.get("turn_posture") or ""),
    }
    placeholder = marker(conn)
    conn.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id,message_id,target_session_id,attempt_kind,adapter_revision,"
        "started_at,completed_at,result_code,evidence) "
        f"VALUES ({','.join(placeholder for _ in range(9))}) "
        "ON CONFLICT(attempt_id) DO NOTHING",
        (
            str(
                uuid5(
                    NAMESPACE_URL,
                    f"yoke:ended-recipient:{message_id}:{session_id}",
                )
            ),
            message_id,
            session_id,
            "wake_relay",
            _ADAPTER_REVISION,
            timestamp(now),
            timestamp(now),
            result_code,
            redacted_evidence(evidence),
        ),
    )


__all__ = [
    "CANCEL_RECOVERY",
    "RECIPIENT_ENDED_RESULT",
    "RECIPIENT_TERMINATED_RESULT",
    "cancel_recovery",
    "recipient_has_no_delivery_route",
    "skip_ended_recipient",
]
