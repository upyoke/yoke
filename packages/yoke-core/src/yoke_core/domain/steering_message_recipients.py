"""Durable rows for messages addressed to the steering role.

A role-addressed message is recorded once, here, whether or not a seat was
live when it was sent. That single row is what makes the address survive a
handoff: it carries the scope the message belongs to and the sender's item,
so any later seat can ask the coverage rule whether the message is its
business, and nothing has to be redirected by hand.

The row moves through three states. ``awaiting_seat`` means no live seat
covered it -- the message is parked, not lost, and no session was asked to
receive it. ``delivered`` names the seat that holds it now; that seat also
holds an ordinary session receipt, so the delivery hook injects it. ``acknowledged``
records that seat acting on it and settles the row for every later handoff.
A seat that ends, or releases its claim, without acknowledging or answering
leaves its delivered row drainable again: the message outlives the seat, so
the successor picks it up rather than the operator re-sending it. A message
cancelled or past its expiry settles its row in every read, whatever the
stored state says.
"""

from __future__ import annotations

from yoke_contracts.timestamps import parse_instant, utc_now

from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.session_message_receipt_expiry import steering_open_sql

import json
from datetime import datetime
from typing import Any, Mapping, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.actor_message_recipient_schema import (
    TABLE as RECIPIENT_TABLE,
)
from yoke_core.domain.steering_recipient_candidates import (
    attach_message_bodies,
    load_unsettled_steering_rows,
)
from yoke_core.domain.steering_scope_coverage import steering_scope_covers
from yoke_core.domain.steering_scope_membership import (
    apply_item_document,
    item_document_links,
)


TABLE = RECIPIENT_TABLE
STEERING_KIND = "steering"

STATE_AWAITING_SEAT = "awaiting_seat"
STATE_DELIVERED = "delivered"
STATE_ACKNOWLEDGED = "acknowledged"


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _encode(scope: Mapping[str, Any]) -> str:
    return json.dumps(dict(scope), sort_keys=True, separators=(",", ":"))


def decode_steering_scope(raw: Any) -> dict[str, Any]:
    """The scope object one stored role-addressed row belongs to."""
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


def row_coverage_target(
    conn: Any,
    row: Mapping[str, Any],
    *,
    links: Mapping[int, tuple[int, str]] | None = None,
) -> dict[str, Any]:
    """The addressed work one stored row represents, for the coverage rule.

    The sender's item is stored; the document that item belongs to is read
    live, because a link written after the message was sent still decides
    which seat the message is now the business of. Pass *links* when
    describing a set of rows so that read happens once for the set.
    """
    target = decode_steering_scope(row.get("steering_scope"))
    item_id = row.get("sender_item_id")
    if item_id is None:
        return target
    target["item_id"] = int(item_id)
    return apply_item_document(conn, target, int(item_id), links=links)


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
    stamp = instant_parameter(conn, created_at)
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
        asked_at=parse_instant(row["sent_at"]),
    )


def awaiting_seat_rows(
    conn: Any,
    *,
    scope: Mapping[str, Any],
    project_id: int,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Open rows this scope covers that no live seat acts on, without bodies.

    A delivered row whose seat is still live was already dropped in SQL;
    what remains of it here is a seat that ended or released its claim.
    """
    rows = load_unsettled_steering_rows(
        conn, project_id, scope, now=utc_now() if now is None else now
    )
    if not rows:
        return []
    item_ids = [
        int(row["sender_item_id"])
        for row in rows
        if row.get("sender_item_id") is not None
    ]
    links = item_document_links(conn, item_ids)
    drainable: list[dict[str, Any]] = []
    for row in rows:
        if not steering_scope_covers(
            scope, row_coverage_target(conn, row, links=links)
        ):
            continue
        if row["state"] != STATE_AWAITING_SEAT and _seat_answered(conn, row):
            continue
        drainable.append(row)
    return drainable


def drainable_rows(
    conn: Any,
    *,
    scope: Mapping[str, Any],
    project_id: int,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Role-addressed rows in this scope that no live seat is acting on.

    Parked rows are the obvious case. The other is an unacknowledged row
    whose seat ended or released without answering: the sender is waiting
    on a reply that can no longer arrive. Acknowledgement, cancellation and
    expiry settle the row permanently.
    """
    return attach_message_bodies(
        conn,
        awaiting_seat_rows(conn, scope=scope, project_id=project_id, now=now),
    )


def session_awaiting_seat_reply(
    conn: Any, session_id: str, *, now: datetime | None = None
) -> dict[str, Any] | None:
    """The unanswered question this session asked the steering role, if any.

    Asked, not merely said. A worker's terminal report is the overwhelmingly
    common thing to send a seat and it waits on nothing, so counting it would
    keep every finished worker's row alive forever -- the opposite of what
    reading this predicate is for. :func:`message_asks` draws that line, and
    an acknowledged row, a cancelled or expired message, or an answer that
    already came back settles the rest.
    """
    from yoke_core.domain.steering_fleet_report_dead_waits import message_asks

    marker = _marker(conn)
    still_open, open_params = steering_open_sql(
        marker, instant_parameter(conn, utc_now() if now is None else now)
    )
    rows = conn.execute(
        "SELECT r.message_id AS message_id, r.state AS state, "
        "m.body AS body, m.created_at AS sent_at, "
        "m.sender_session_id AS sender_session_id, "
        "r.seat_session_id AS seat_session_id "
        f"FROM {TABLE} r "
        "JOIN session_messages m ON m.message_id = r.message_id "
        f"WHERE r.recipient_kind = {marker} AND m.sender_session_id = {marker} "
        f"AND {still_open} AND r.state <> {marker} "
        "ORDER BY m.created_at DESC, r.message_id DESC",
        (STEERING_KIND, str(session_id), *open_params, STATE_ACKNOWLEDGED),
    ).fetchall()
    for raw in rows:
        row = dict(raw)
        if not message_asks(row.get("body")):
            continue
        if row.get("seat_session_id") and _seat_answered(conn, row):
            continue
        return {"message_id": str(row["message_id"]), "state": str(row["state"])}
    return None


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
            instant_parameter(conn, now),
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
    "awaiting_seat_rows",
    "decode_steering_scope",
    "drainable_rows",
    "holding_seat_session_id",
    "record_steering_recipient",
    "role_addressed_message_ids",
    "row_coverage_target",
    "session_awaiting_seat_reply",
]
