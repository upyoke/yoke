"""Receipt mutations: a recipient acting on a message, a sender revoking one.

Acknowledgement is the recipient's own claim that it received the message,
so it is always self-only. A role-addressed message has two ways of being
one: the seat that was live when it was sent holds an ordinary session
receipt, while a seat that inherited it on acquire holds only the role row,
because a parked message was never delivered to any session. Both are the
holder acknowledging its own mail, so both acknowledge, and a caller that
is neither is still refused.

Cancellation belongs to the sender, or to an administrator of every project
the message reached -- anything narrower would let one project's admin
revoke a message that also went elsewhere.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from yoke_core.domain.actor_message_recipients import acknowledge_actor_recipient
from yoke_core.domain.session_message_reads import message_details
from yoke_core.domain.session_message_store import (
    acknowledge_recipient,
    cancel_message_rows,
)
from yoke_core.domain.session_message_types import SessionMessageError, utc_now
from yoke_core.domain.steering_message_recipients import (
    acknowledge_steering_recipient,
)


def acknowledge_message(
    conn: Any,
    *,
    message_id: str,
    session_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    from yoke_core.domain.session_message_delivery import expire_due_recipients

    expire_due_recipients(conn, now=now)
    acknowledged_at = now or utc_now()
    seated = acknowledge_steering_recipient(
        conn,
        message_id=message_id,
        session_id=session_id,
        now=acknowledged_at,
    )
    try:
        details = acknowledge_recipient(
            conn,
            message_id=message_id,
            session_id=session_id,
            acknowledged_at=acknowledged_at,
        )
    except SessionMessageError:
        if not seated:
            raise
        conn.commit()
        return message_details(conn, message_id)
    recipient = next(
        (
            row
            for row in details.get("recipients", [])
            if str(row.get("session_id") or "") == session_id
        ),
        None,
    )
    if recipient is not None:
        from yoke_core.domain.session_private_route_qualification import (
            PrivateRouteQualificationError,
            consume_qualification_grant,
            qualification_for_message,
        )

        try:
            grant = qualification_for_message(
                conn,
                {"message_id": message_id, **recipient},
                operation="message_active",
                route="hook",
                now=now,
            )
            if grant is not None:
                consume_qualification_grant(conn, grant)
        except PrivateRouteQualificationError:
            # Qualification is acceptance evidence, never product ack authority.
            # A raced, expired, or revoked grant stays unproven without making
            # an otherwise valid delivered message impossible to acknowledge.
            pass
    conn.commit()
    return details


def acknowledge_actor_message(
    conn: Any,
    *,
    message_id: str,
    actor_id: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    acknowledge_actor_recipient(
        conn, message_id=message_id, actor_id=actor_id, read_at=now
    )
    conn.commit()
    return message_details(conn, message_id)


def cancel_message(
    conn: Any,
    *,
    message_id: str,
    actor_id: int,
    reason: str = "cancelled_by_sender",
    now: datetime | None = None,
) -> dict[str, Any]:
    details = message_details(conn, message_id)
    sender = int(details["sender_actor_id"]) == actor_id
    project_ids = {
        int(recipient["project_id"])
        for recipient in details.get("recipients", [])
        if recipient.get("project_id") is not None
    }
    if not sender:
        from yoke_core.domain.actor_permissions import (
            PERM_PROJECT_ADMIN,
            permission_decision,
        )

        administers_all = bool(project_ids) and all(
            permission_decision(
                conn,
                actor_id=actor_id,
                project_id=project_id,
                permission_key=PERM_PROJECT_ADMIN,
            ).allowed
            for project_id in project_ids
        )
    else:
        administers_all = False
    if not sender and not administers_all:
        raise SessionMessageError(
            "cancel_forbidden",
            "only the sender or an administrator of every target project may cancel",
        )
    if administers_all and reason == "cancelled_by_sender":
        reason = "cancelled_by_project_admin"
    cancelled = cancel_message_rows(
        conn,
        message_id=message_id,
        actor_id=actor_id,
        reason=reason,
        cancelled_at=now or utc_now(),
    )
    conn.commit()
    return cancelled

__all__ = [
    "acknowledge_actor_message",
    "acknowledge_message",
    "cancel_message",
]
