"""Durable rows for messages addressed to the steering role.

A role-addressed message is recorded once, here, whether or not a seat was
live when it was sent. That single row is what makes the address survive a
handoff: it carries the scope the message belongs to and the sender's item,
so any later seat can ask the coverage rule whether the message is its
business, and nothing has to be redirected by hand.

The row moves through three states. ``awaiting_seat`` means no live seat
covered it -- the message is parked, not lost, and no session was asked to
receive it. ``delivered`` names the seat that holds it now. ``acknowledged``
records that seat acting on it and settles the row for every later handoff.
A seat that ends without acknowledging or answering leaves its delivered
row drainable again: the message outlives the session, so the successor
picks it up rather than the operator re-sending it.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.actor_message_recipient_schema import (
    TABLE as RECIPIENT_TABLE,
)
from yoke_core.domain.session_message_types import timestamp
from yoke_core.domain.steering_scope_coverage import steering_scope_covers


TABLE = RECIPIENT_TABLE
STEERING_KIND = "steering"

STATE_AWAITING_SEAT = "awaiting_seat"
STATE_DELIVERED = "delivered"
STATE_ACKNOWLEDGED = "acknowledged"


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _encode(scope: Mapping[str, Any]) -> str:
    return json.dumps(dict(scope), sort_keys=True, separators=(",", ":"))


def _decode(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


def row_coverage_target(row: Mapping[str, Any]) -> dict[str, Any]:
    """The addressed work one stored row represents, for the coverage rule."""
    target = _decode(row.get("steering_scope"))
    item_id = row.get("sender_item_id")
    if item_id is not None:
        target["item_id"] = int(item_id)
    return target


def record_steering_recipient(
    conn: Any,
    *,
    message_id: str,
    scope: Mapping[str, Any],
    project_id: int,
    sender_item_id: int | None,
    seat_session_id: str | None,
    seat_claim_id: int | None,
    created_at: datetime,
) -> None:
    """Record one role-addressed message, seated or parked."""
    marker = _marker(conn)
    stamp = timestamp(created_at)
    seated = seat_session_id is not None
    conn.execute(
        f"INSERT INTO {TABLE} (message_id, recipient_kind, actor_id, state, "
        "steering_scope, sender_item_id, project_id, seat_session_id, "
        "seat_claim_id, created_at, delivered_at) "
        f"VALUES ({', '.join(marker for _ in range(11))})",
        (
            message_id,
            STEERING_KIND,
            None,
            STATE_DELIVERED if seated else STATE_AWAITING_SEAT,
            _encode(scope),
            int(sender_item_id) if sender_item_id is not None else None,
            int(project_id),
            seat_session_id,
            int(seat_claim_id) if seat_claim_id is not None else None,
            stamp,
            stamp if seated else None,
        ),
    )


def _rows_for_project(conn: Any, project_id: int) -> list[dict[str, Any]]:
    marker = _marker(conn)
    rows = conn.execute(
        f"SELECT r.message_id AS message_id, r.state AS state, "
        "r.steering_scope AS steering_scope, r.sender_item_id AS sender_item_id, "
        "r.project_id AS project_id, r.seat_session_id AS seat_session_id, "
        "r.created_at AS created_at, m.body AS body, "
        "m.sender_session_id AS sender_session_id, "
        "m.created_at AS sent_at, m.cancelled_at AS cancelled_at, "
        "seat.ended_at AS seat_ended_at, seat.terminated_at AS seat_terminated_at "
        f"FROM {TABLE} r "
        "JOIN session_messages m ON m.message_id = r.message_id "
        "LEFT JOIN harness_sessions seat ON seat.session_id = r.seat_session_id "
        f"WHERE r.recipient_kind = {marker} AND r.project_id = {marker} "
        "ORDER BY m.created_at DESC, r.message_id DESC",
        (STEERING_KIND, int(project_id)),
    ).fetchall()
    return [dict(row) for row in rows]


def _seat_still_live(row: Mapping[str, Any]) -> bool:
    if not row.get("seat_session_id"):
        return False
    return not (row.get("seat_ended_at") or row.get("seat_terminated_at"))


def _seat_answered(conn: Any, row: Mapping[str, Any]) -> bool:
    """Did the seat that held this row reply to the sender afterwards?

    A seat that answered and then ended did its job; re-handing the message
    to a successor would ask for the answer a second time.
    """
    from yoke_core.domain.steering_fleet_report_dead_waits import answered_after

    asker = str(row.get("sender_session_id") or "")
    answerer = str(row.get("seat_session_id") or "")
    if not asker or not answerer:
        return False
    return answered_after(
        conn,
        answerer=answerer,
        asker=asker,
        asked_at=str(row.get("sent_at") or ""),
    )


def drainable_rows(
    conn: Any,
    *,
    scope: Mapping[str, Any],
    project_id: int,
) -> list[dict[str, Any]]:
    """Role-addressed rows in this scope that no live seat is acting on.

    Parked rows are the obvious case. The other is an unacknowledged row
    whose seat ended without answering: the sender is waiting on a reply
    that can no longer arrive. Acknowledgement settles the row permanently.
    """
    drainable: list[dict[str, Any]] = []
    for row in _rows_for_project(conn, project_id):
        if row.get("cancelled_at"):
            continue
        if not steering_scope_covers(scope, row_coverage_target(row)):
            continue
        if row["state"] == STATE_AWAITING_SEAT:
            drainable.append(row)
            continue
        if row["state"] == STATE_ACKNOWLEDGED:
            continue
        if _seat_still_live(row) or _seat_answered(conn, row):
            continue
        drainable.append(row)
    return drainable


def awaiting_seat_count(conn: Any, *, project_id: int, scope: Mapping[str, Any]) -> int:
    """How many role-addressed messages in this scope have no live seat."""
    return len(drainable_rows(conn, scope=scope, project_id=project_id))


def hand_to_seat(
    conn: Any,
    *,
    rows: Sequence[Mapping[str, Any]],
    session_id: str,
    claim_id: int,
    now: datetime,
) -> int:
    """Mark drained rows delivered to the seat that just took the scope."""
    marker = _marker(conn)
    stamp = timestamp(now)
    handed = 0
    for row in rows:
        cursor = conn.execute(
            f"UPDATE {TABLE} SET state = {marker}, seat_session_id = {marker}, "
            f"seat_claim_id = {marker}, delivered_at = {marker}, "
            "acknowledged_at = NULL "
            f"WHERE recipient_kind = {marker} AND message_id = {marker}",
            (
                STATE_DELIVERED,
                str(session_id),
                int(claim_id),
                stamp,
                STEERING_KIND,
                str(row["message_id"]),
            ),
        )
        handed += int(cursor.rowcount or 0)
    return handed


def acknowledge_steering_recipient(
    conn: Any,
    *,
    message_id: str,
    session_id: str,
    now: datetime,
) -> bool:
    """Record the seat holding a role-addressed message acting on it."""
    marker = _marker(conn)
    cursor = conn.execute(
        f"UPDATE {TABLE} SET state = {marker}, acknowledged_at = {marker} "
        f"WHERE recipient_kind = {marker} AND message_id = {marker} "
        f"AND seat_session_id = {marker} AND state = {marker}",
        (
            STATE_ACKNOWLEDGED,
            timestamp(now),
            STEERING_KIND,
            str(message_id),
            str(session_id),
            STATE_DELIVERED,
        ),
    )
    return bool(cursor.rowcount)


def holding_seat_session_id(conn: Any, message_id: str) -> str | None:
    """The seat a role-addressed message is currently sitting with, if any."""
    marker = _marker(conn)
    row = conn.execute(
        f"SELECT seat_session_id FROM {TABLE} "
        f"WHERE recipient_kind = {marker} AND message_id = {marker}",
        (STEERING_KIND, str(message_id)),
    ).fetchone()
    if row is None:
        return None
    seat = dict(row).get("seat_session_id")
    return str(seat) if seat else None


def role_addressed_message_ids(conn: Any, message_ids: Sequence[str]) -> set[str]:
    """Which of these messages are addressed to the steering role."""
    if not message_ids:
        return set()
    marker = _marker(conn)
    slots = ",".join(marker for _ in message_ids)
    rows = conn.execute(
        f"SELECT message_id FROM {TABLE} "
        f"WHERE recipient_kind = {marker} AND message_id IN ({slots})",
        (STEERING_KIND, *[str(value) for value in message_ids]),
    ).fetchall()
    return {str(dict(row)["message_id"]) for row in rows}


__all__ = [
    "STATE_ACKNOWLEDGED",
    "STATE_AWAITING_SEAT",
    "STATE_DELIVERED",
    "STEERING_KIND",
    "TABLE",
    "acknowledge_steering_recipient",
    "awaiting_seat_count",
    "drainable_rows",
    "hand_to_seat",
    "holding_seat_session_id",
    "record_steering_recipient",
    "role_addressed_message_ids",
    "row_coverage_target",
]
