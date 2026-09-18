"""Recipient-backed idempotency for explicit native session wakes.

A wake already on its way is the thing this module protects: two natives
racing the same conversation is the failure, so a second request is refused
while the first is still moving. Every reason it can give is therefore a
claim that something is *about* to happen.

A queued explicit receipt nothing ever attempts breaks that claim. The
delivery plane can decline to attempt one — the route it needs is gone, the
recipient looks like a turn in flight, its machine's relay is not reporting
— and the receipt then sits ``pending`` at zero attempts for as long as the
envelope lives. Read as "in flight" it refuses every later wake for the same
session, so the one operator move that could recover the session is the one
move the deadlock blocks. One such receipt held a machine's worth of workers
unreachable until the message aged out.

So being queued buys a bounded wait, not an unbounded one. Inside the
project's wake acknowledgement grace window a queued explicit receipt still
blocks, because an attempt is genuinely owed and about to be made. Past that
window it is stale rather than in flight: :func:`stale_queued_wakes` names it
so the caller can release it and try again, and :func:`recent_wake_blocker`
stops counting it as a reason to refuse.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.session_explicit_wake import explicit_stopped_wake_requested
from yoke_core.domain.session_message_types import parse_timestamp, row_dict, timestamp


#: What the recipient row says when its wake is queued and unattempted, on
#: the blocker and on the fleet report's row for the same receipt.
WAKE_QUEUED_REASON = "wake_queued"


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _open_receipts(conn: Any, *, session_id: str, now: datetime) -> list[dict[str, Any]]:
    """Every receipt for this session an attempt could still be owed on."""
    marker = _marker(conn)
    rows = conn.execute(
        "SELECT r.message_id,r.state,r.wake_attempt_count,r.last_wake_at,"
        "r.routing_snapshot,m.created_at,EXISTS (SELECT 1 FROM "
        "session_message_attempts a WHERE a.message_id=r.message_id AND "
        "a.target_session_id=r.session_id AND "
        "a.attempt_kind IN ('wake_relay','wake_broker') AND "
        "a.completed_at IS NULL) AS open_attempt "
        "FROM session_message_recipients r JOIN session_messages m "
        "ON m.message_id=r.message_id "
        f"WHERE r.session_id={marker} AND r.state IN ('pending','injected') "
        "AND m.cancelled_at IS NULL AND m.expires_at>"
        + marker
        + " ORDER BY m.created_at,r.message_id",
        (session_id, timestamp(now)),
    ).fetchall()
    return [row_dict(raw) for raw in rows]


def _queued_explicit(row: dict[str, Any]) -> bool:
    """Whether this receipt is an explicit wake nothing has attempted yet."""
    return (
        int(row.get("wake_attempt_count") or 0) == 0
        and str(row.get("state") or "") == "pending"
        and not bool(row.get("open_attempt"))
        and explicit_stopped_wake_requested(row.get("routing_snapshot"))
    )


def _receipt_facts(row: dict[str, Any], *, reason: str, retry_at: Any) -> dict[str, Any]:
    return {
        "message_id": str(row["message_id"]),
        "wake_attempt_count": int(row.get("wake_attempt_count") or 0),
        "last_wake_at": row.get("last_wake_at"),
        "retry_after": timestamp(retry_at) if retry_at else None,
        "reason": reason,
    }


def stale_queued_wakes(
    conn: Any,
    *,
    session_id: str,
    now: datetime,
    grace_seconds: int,
    exclude_message_id: str | None = None,
) -> list[dict[str, Any]]:
    """Explicit wake receipts whose attempt was owed and never made.

    The window is the same acknowledgement grace a live attempt is given,
    counted from the envelope's own creation: after it, the delivery plane
    has had its chance and a receipt still at zero attempts is not one more
    poll away. Returning it is not a verdict on why — the caller releases it
    and asks for a fresh wake, and whatever refused the first attempt refuses
    that one by name, with its own recovery, instead of silently blocking.
    """
    window = timedelta(seconds=max(0, int(grace_seconds)))
    stale: list[dict[str, Any]] = []
    for row in _open_receipts(conn, session_id=session_id, now=now):
        if str(row["message_id"]) == exclude_message_id:
            continue
        if not _queued_explicit(row):
            continue
        created = parse_timestamp(row.get("created_at"))
        if created is None or created + window > now:
            continue
        stale.append(_receipt_facts(row, reason=WAKE_QUEUED_REASON, retry_at=None))
    return stale


def recent_wake_blocker(
    conn: Any,
    *,
    session_id: str,
    now: datetime,
    grace_seconds: int,
    exclude_message_id: str | None = None,
    include_queued_explicit: bool = False,
) -> dict[str, Any] | None:
    """Return the receipt that prevents another native wake right now.

    A caller may exclude its deterministic message id so an exact retry can
    deduplicate. New explicit requests also treat an older still-pending
    queued explicit receipt as in flight, closing the gap before a relay
    has claimed it -- but only inside ``grace_seconds`` of that envelope's
    creation, after which :func:`stale_queued_wakes` owns it and this
    returns nothing for it. An already-injected receipt is delivered, not
    queued, even when it is unacknowledged and has no native wake attempt.
    A writer must hold the target harness-session row lock across this read
    and its insert; :func:`request_session_wake` does so.
    """
    grace = timedelta(seconds=max(0, int(grace_seconds)))
    for row in _open_receipts(conn, session_id=session_id, now=now):
        if str(row["message_id"]) == exclude_message_id:
            continue
        attempt_count = int(row.get("wake_attempt_count") or 0)
        last_wake = parse_timestamp(row.get("last_wake_at"))
        retry_at = last_wake + grace if last_wake is not None else None
        reason = None
        if bool(row.get("open_attempt")):
            reason = "wake_attempt_in_progress"
        elif attempt_count > 0 and retry_at is not None and retry_at > now:
            reason = "wake_grace_window"
        elif include_queued_explicit and _queued_explicit(row):
            created = parse_timestamp(row.get("created_at"))
            if created is not None and created + grace <= now:
                continue
            reason = WAKE_QUEUED_REASON
            retry_at = created + grace if created is not None else None
        if reason:
            return _receipt_facts(row, reason=reason, retry_at=retry_at)
    return None


__all__ = ["WAKE_QUEUED_REASON", "recent_wake_blocker", "stale_queued_wakes"]
