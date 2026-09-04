"""How a role-addressed recipient reads to every surface that shows it.

A message sent to the steering role has a recipient even when no session
is holding it: the durable row in
:mod:`yoke_core.domain.steering_message_recipients`. Send, preview, get
and list each used to describe delivery only in terms of sessions, so a
send that parked correctly reported zero recipients and said nothing
about the seat it was waiting for -- indistinguishable, to the sender,
from a message that went nowhere.

This module is the one shape those surfaces render instead. It carries
the recipient's real state, the scope it belongs to, the seat holding it
when one does, and one sentence saying which of those is true. The CLI
displays it beside session and human recipients; the JSON envelope
carries the same fields, so nothing has to re-derive the sentence.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_core.domain.steering_message_recipients import (
    STATE_ACKNOWLEDGED,
    STATE_AWAITING_SEAT,
    STATE_DELIVERED,
    STEERING_KIND,
    TABLE,
    decode_steering_scope,
)


#: Party name for a recipient that is a role rather than a session.
PARTY_LABEL = "steering seat"


def _summary(state: str, scope_label: str, seat_session_id: Optional[str]) -> str:
    if state == STATE_AWAITING_SEAT:
        return (
            f"queued for the steering seat covering {scope_label}; no live "
            "seat covers it yet, and the next covering acquire drains it"
        )
    verb = "acknowledged by" if state == STATE_ACKNOWLEDGED else "delivered to"
    return f"{verb} the steering seat covering {scope_label} ({seat_session_id})"


def steering_recipient(
    conn: Any,
    *,
    state: str,
    scope: Mapping[str, Any],
    project_id: int,
    sender_item_id: Optional[int],
    seat_session_id: Optional[str],
    delivered_at: Any = None,
    acknowledged_at: Any = None,
) -> dict[str, Any]:
    """Describe one role-addressed recipient for readers and renderers."""
    from yoke_core.domain.steering_fleet_report_compose import (
        steering_scope_descriptor,
    )

    scope_label = steering_scope_descriptor(conn, scope)
    seated = seat_session_id is not None
    return {
        "kind": STEERING_KIND,
        "state": state,
        "scope": dict(scope),
        "scope_label": scope_label,
        "project_id": int(project_id),
        "sender_item_id": sender_item_id,
        "session_id": seat_session_id,
        "label": PARTY_LABEL,
        "executor_surface": PARTY_LABEL,
        "messageability": {
            "messageable": seated,
            "reason": None if seated else STATE_AWAITING_SEAT,
        },
        "delivered_at": delivered_at,
        "acknowledged_at": acknowledged_at,
        "summary": _summary(state, scope_label, seat_session_id),
    }


def stored_steering_recipient(conn: Any, message_id: str) -> dict[str, Any] | None:
    """The recorded role-addressed recipient of one message, if it has one."""
    from yoke_core.domain import db_backend

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT state, steering_scope, project_id, sender_item_id, "
        f"seat_session_id, delivered_at, acknowledged_at FROM {TABLE} "
        f"WHERE recipient_kind = {marker} AND message_id = {marker}",
        (STEERING_KIND, str(message_id)),
    ).fetchone()
    if row is None:
        return None
    record = dict(row)
    seat = record.get("seat_session_id")
    return steering_recipient(
        conn,
        state=str(record["state"]),
        scope=decode_steering_scope(record["steering_scope"]),
        project_id=int(record["project_id"]),
        sender_item_id=(
            None
            if record.get("sender_item_id") is None
            else int(record["sender_item_id"])
        ),
        seat_session_id=str(seat) if seat else None,
        delivered_at=record.get("delivered_at"),
        acknowledged_at=record.get("acknowledged_at"),
    )


def previewed_steering_recipient(
    conn: Any,
    address: Any,
    *,
    seat_session_id: Optional[str],
) -> dict[str, Any]:
    """What a role-addressed send would record, before anything is stored."""
    return steering_recipient(
        conn,
        state=STATE_DELIVERED if seat_session_id else STATE_AWAITING_SEAT,
        scope=address.scope,
        project_id=address.project_id,
        sender_item_id=address.sender_item_id,
        seat_session_id=seat_session_id,
    )


__all__ = [
    "PARTY_LABEL",
    "previewed_steering_recipient",
    "steering_recipient",
    "stored_steering_recipient",
]
