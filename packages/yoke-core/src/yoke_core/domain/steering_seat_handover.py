"""Hand role-addressed messages to a seat the way a live send reaches it.

A message sent while a seat is live gets two rows: the durable role row and
the seat's session receipt, which is what the delivery hook injects and the
reminder re-presents. A message handed over later -- parked with no seat, or
left behind by a seat that ended -- gets exactly the same pair here, so the
new seat receives it through the same hook instead of only reading a count.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from yoke_contracts.session_control.recipient_selector import RecipientSelector
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.session_message_recipient_rows import insert_session_receipt
from yoke_core.domain.steering_message_recipients import (
    STATE_ACKNOWLEDGED,
    STATE_DELIVERED,
    STEERING_KIND,
    TABLE,
    row_coverage_target,
)


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def cancel_session_receipt(
    conn: Any,
    *,
    message_id: str,
    session_id: str,
    now: datetime,
) -> None:
    """Withdraw one session's unacknowledged receipt for a message."""
    if not session_id:
        return
    marker = _marker(conn)
    conn.execute(
        "UPDATE session_message_recipients "
        f"SET state = {marker}, cancelled_at = {marker} "
        f"WHERE message_id = {marker} AND session_id = {marker} "
        f"AND state <> {marker}",
        (
            "cancelled",
            instant_parameter(conn, parse_instant(now)),
            message_id,
            session_id,
            "acknowledged",
        ),
    )


def _give_seat_receipt(
    conn: Any,
    row: Mapping[str, Any],
    *,
    seat_session_id: str,
    now: datetime,
) -> bool:
    """Write the seat's receipt through the same resolution a send uses."""
    from yoke_core.domain.session_message_selectors import resolve_recipients

    recipients = [
        recipient
        for recipient in resolve_recipients(
            conn,
            RecipientSelector(steering=True),
            now=now,
            steering_target=row_coverage_target(conn, row),
        )
        if recipient.session_id == seat_session_id
    ]
    for recipient in recipients:
        insert_session_receipt(
            conn,
            message_id=str(row["message_id"]),
            recipient=recipient,
            created_at=now,
            wake_after=now,
        )
    return bool(recipients)


def hand_to_seat(
    conn: Any,
    *,
    rows: Sequence[Mapping[str, Any]],
    session_id: str,
    claim_id: int,
    now: datetime,
) -> list[dict[str, Any]]:
    """Deliver each row to the seat: role row, then the seat's receipt.

    Returns one entry per message actually handed, with ``receipt`` false
    when the seat did not resolve as a recipient and so cannot be injected;
    the caller reports those rather than implying delivery.
    """
    marker = _marker(conn)
    stamp = instant_parameter(conn, now)
    lock = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    handed: list[dict[str, Any]] = []
    for row in rows:
        message_id = str(row["message_id"])
        conn.execute(
            f"SELECT state FROM {TABLE} "
            f"WHERE recipient_kind = {marker} AND message_id = {marker}" + lock,
            (STEERING_KIND, message_id),
        )
        cursor = conn.execute(
            f"UPDATE {TABLE} SET state = {marker}, seat_session_id = {marker}, "
            f"seat_claim_id = {marker}, delivered_at = {marker}, "
            "acknowledged_at = NULL "
            f"WHERE recipient_kind = {marker} AND message_id = {marker} "
            f"AND state <> {marker}",
            (
                STATE_DELIVERED,
                str(session_id),
                int(claim_id),
                stamp,
                STEERING_KIND,
                message_id,
                STATE_ACKNOWLEDGED,
            ),
        )
        if not cursor.rowcount:
            continue
        previous = str(row.get("seat_session_id") or "")
        if previous and previous != str(session_id):
            cancel_session_receipt(
                conn, message_id=message_id, session_id=previous, now=now
            )
        receipt = _give_seat_receipt(
            conn, row, seat_session_id=str(session_id), now=now
        )
        handed.append({"message_id": message_id, "receipt": receipt})
    return handed


__all__ = ["cancel_session_receipt", "hand_to_seat"]
