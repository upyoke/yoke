"""Durable record of why an injectable hook attached no pending envelope.

A hook that finds nothing to inject returns silently, and for almost every
event that is correct: most events reach a session whose inbox is empty.
The expensive case is the other one — a receipt sitting ``pending`` for this
exact session while an event passes through and attaches nothing. That pair
is a delivery failure, and while it left no trace the only way to reach it
was to infer a mechanism from an absence: a woken session recorded a resume,
an idle turn, and an ``injection_count`` that never moved, with nothing
anywhere saying which step declined.

The record is one ``session_message_attempts`` row per receipt, in the same
table an operator already reads to follow a message, carrying the reason and
the event that declined. Its identifier is derived from the receipt, the
session, the event, and the reason, so a chatty event class records the fact
once and every later invocation folds into that row instead of growing one
per hook.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from yoke_core.domain import db_backend
from yoke_core.domain.json_helper import dumps_compact
from yoke_core.domain.session_message_delivery import _begin_mutation
from yoke_core.domain.session_message_types import timestamp, utc_now


DELIVERY_PROBE_ADAPTER_REVISION = "session-message-delivery-probe-v1"

# Why an injectable evaluation attached nothing. Each names one declining
# step, because "no envelope arrived" is the symptom all three produce and
# the operator needs to know which one to go and fix. All three are facts
# about the moment — the session row, a lease race, a failing statement —
# so none of them can be recovered afterwards from configuration.
PROBE_SESSION_NOT_DELIVERABLE = "probe_session_not_deliverable"
PROBE_NO_LEASABLE_RECEIPT = "probe_no_leasable_receipt"
PROBE_LEASE_FAILED = "probe_lease_failed"

PROBE_REASONS = frozenset(
    {
        PROBE_SESSION_NOT_DELIVERABLE,
        PROBE_NO_LEASABLE_RECEIPT,
        PROBE_LEASE_FAILED,
    }
)

_MAX_DETAIL_LENGTH = 64


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def bounded_detail(value: object) -> str:
    """Return a short, non-secret diagnostic token, or ``""``.

    Callers pass a classification — an exception class name, a capability
    label — never a message, because a probe row is read by whoever can see
    the control plane and an exception's text can carry a payload.
    """
    if not isinstance(value, str):
        return ""
    cleaned = "".join(
        character
        for character in value.strip()
        if character.isalnum() or character in {"_", ".", "-"}
    )
    return cleaned[:_MAX_DETAIL_LENGTH]


def probe_attempt_id(
    *,
    message_id: str,
    session_id: str,
    hook_event: str,
    reason: str,
) -> str:
    """Return the stable identifier one (receipt, event, reason) fact owns."""
    return str(
        uuid5(
            NAMESPACE_URL,
            f"yoke:delivery-probe:{message_id}:{session_id}:{hook_event}:{reason}",
        )
    )


def record_undelivered_receipts(
    conn: Any,
    *,
    session_id: str,
    hook_event: str,
    reason: str,
    detail: object = "",
    now: datetime | None = None,
) -> int:
    """Record why every still-pending receipt for one session went unattached.

    Returns the number of receipts the reason was recorded against — zero
    when the session had nothing pending, which is the ordinary case and the
    one that deliberately writes nothing at all.
    """
    if reason not in PROBE_REASONS:
        raise ValueError(f"unknown delivery probe reason: {reason}")
    session = str(session_id or "").strip()
    if not session:
        return 0
    current = now or utc_now()
    stamp = timestamp(current)
    marker = _p(conn)
    # The reason itself is the row's ``result_code``; evidence carries only
    # what that column cannot say. Both keys are on the shared read
    # whitelist, so the operator-facing message view shows them.
    evidence = dumps_compact(
        {"hook_event": hook_event, "probe_detail": bounded_detail(detail)}
    )
    _begin_mutation(conn)
    try:
        rows = conn.execute(
            "SELECT r.message_id FROM session_message_recipients r "
            "JOIN session_messages m ON m.message_id=r.message_id "
            f"WHERE r.session_id={marker} AND r.state='pending' "
            f"AND m.cancelled_at IS NULL AND m.expires_at>{marker}",
            (session, stamp),
        ).fetchall()
        for row in rows:
            message_id = str(row[0])
            conn.execute(
                "INSERT INTO session_message_attempts "
                "(attempt_id,message_id,target_session_id,attempt_kind,"
                "adapter_revision,started_at,completed_at,result_code,evidence) "
                f"VALUES ({','.join(marker for _ in range(9))}) "
                "ON CONFLICT(attempt_id) DO NOTHING",
                (
                    probe_attempt_id(
                        message_id=message_id,
                        session_id=session,
                        hook_event=hook_event,
                        reason=reason,
                    ),
                    message_id,
                    session,
                    "hook",
                    DELIVERY_PROBE_ADAPTER_REVISION,
                    stamp,
                    stamp,
                    reason,
                    evidence,
                ),
            )
        conn.commit()
        return len(rows)
    except Exception:
        conn.rollback()
        raise


__all__ = [
    "DELIVERY_PROBE_ADAPTER_REVISION",
    "PROBE_LEASE_FAILED",
    "PROBE_NO_LEASABLE_RECEIPT",
    "PROBE_REASONS",
    "PROBE_SESSION_NOT_DELIVERABLE",
    "bounded_detail",
    "probe_attempt_id",
    "record_undelivered_receipts",
]
