"""Tell a desktop session's operator that a message is waiting on them.

Yoke never resumes an operator-opened desktop conversation, so a message
addressed to one has exactly one way in: the hook that runs on the
operator's next turn. That is a fine route while the person is working and
no route at all while they are away, and nothing in the fleet could tell
the difference — the envelope simply sat there.

So the absence is reported to the one party who can end it. Past the same
acknowledgement grace window every other starvation test uses, the
session's own operator gets an actor-addressed message naming the waiting
conversation and the single action that delivers it: type anything in that
chat. One notice per waiting envelope, keyed so a sweep every few seconds
does not become a mailbox full of the same sentence.

A notice is a derived fact, so it lives exactly as long as the absence it
reports. The envelope's own state ends that absence -- a hook ran, the
seat acknowledged, the message was cancelled or expired, the conversation
ended -- and one predicate decides both directions, so the Inbox can never
keep saying a message is waiting for a message that arrived. Settling
cancels the notice with the reason that ended it and leaves the row where
it is: the history stays readable, and nothing dismisses a decision a
person still owes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from yoke_contracts.session_control.capabilities import native_wake_supported
from yoke_core.domain import db_backend
from yoke_core.domain.actor_message_recipient_schema import (
    TABLE as ACTOR_RECIPIENT_TABLE,
)
from yoke_core.domain.actor_message_recipients import (
    ACTOR_KIND,
    ResolvedActorRecipient,
)
from yoke_core.domain.actor_render import actor_render_label
from yoke_core.domain.actors import SYSTEM_COMPONENT_YOKE_CORE, seed_system_actor
from yoke_core.domain.session_message_authorization import project_policy
from yoke_core.domain.session_message_starvation import undelivered_since_send
from yoke_core.domain.session_message_store import insert_message
from yoke_core.domain.session_message_types import parse_timestamp


#: Prefix of the per-envelope dedupe key, so one waiting message produces
#: one notice however many sweeps observe it.
NOTICE_IDEMPOTENCY_PREFIX = "desktop-operator-wake"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def wake_notice_settled_reason(row: Mapping[str, Any]) -> str | None:
    """Why this envelope no longer needs a person, or ``None`` while it does.

    The facts are the surface's declared wake authority, whether the
    conversation is still open, and the same "no hook has run since the
    send" evidence a native escalation reads. Naming which one answered is
    what the settled notice records, so a reader learns why the card went
    away rather than only that it did.

    The names are held apart on purpose. A receipt that left ``pending``,
    or that a hook attached, is the message actually arriving. A tool call
    after the send is a weaker fact: it proves the person came back to that
    chat, which is exactly what the notice asked them to do, while the
    envelope itself is still waiting on a delivery defect with its own
    probe record. Settling on ``conversation_resumed`` retires the ask
    without claiming a delivery that has not happened, and nothing here
    touches the original receipt either way.
    """
    if native_wake_supported(str(row.get("executor_surface") or "")):
        return "surface_wakes_natively"
    if row.get("ended_at") or row.get("terminated_at"):
        return "target_session_ended"
    if parse_timestamp(row.get("message_created_at")) is None:
        return None
    if undelivered_since_send(row):
        return None
    state = str(row.get("state") or "")
    if state and state != "pending":
        return f"original_{state}"
    if int(row.get("injection_count") or 0) > 0:
        return "original_injected"
    return "conversation_resumed"


def operator_wake_notice_due(
    row: Mapping[str, Any],
    *,
    grace_seconds: int,
    now: datetime,
) -> bool:
    """Whether this receipt is a desktop message its operator has not seen.

    A notice is owed while nothing has settled the envelope and the same
    grace window every other starvation test uses has elapsed.
    """
    if wake_notice_settled_reason(row) is not None:
        return False
    created = parse_timestamp(row.get("message_created_at"))
    return created is not None and created + timedelta(seconds=grace_seconds) <= now


def _operator_actor_id(conn: Any, session_id: str) -> int | None:
    marker = _p(conn)
    row = conn.execute(
        f"SELECT actor_id FROM harness_sessions WHERE session_id={marker}",
        (session_id,),
    ).fetchone()
    return int(row[0]) if row is not None and row[0] is not None else None


def _notice_body(*, session_id: str, surface: str, envelope_id: str) -> str:
    return (
        f"A message is waiting in your {surface} session {session_id} and "
        "Yoke will not open it for you: resuming a desktop conversation "
        "programmatically forks the transcript you are reading, so the wake "
        "is yours. Open that chat and type anything — the next turn's hook "
        f"delivers the pending message ({envelope_id}). Nothing is lost "
        "while it waits; it expires on the project's message expiry."
    )


def notify_operator_to_wake(
    conn: Any,
    row: Mapping[str, Any],
    *,
    now: datetime,
    grace_seconds: int | None = None,
) -> str | None:
    """Record one waiting-message notice for a desktop session's operator.

    Returns the notice's message id when this call created it, and ``None``
    when no notice is owed or one already stands for the same envelope.
    """
    project_id = int(row["project_id"])
    if grace_seconds is None:
        grace_seconds = project_policy(conn, project_id).wake_ack_grace_seconds
    if not operator_wake_notice_due(row, grace_seconds=grace_seconds, now=now):
        return None
    session_id = str(row["session_id"])
    actor_id = _operator_actor_id(conn, session_id)
    if actor_id is None:
        return None
    envelope_id = str(row["message_id"])
    policy = project_policy(conn, project_id)
    details, created = insert_message(
        conn,
        sender_actor_id=seed_system_actor(conn, SYSTEM_COMPONENT_YOKE_CORE),
        sender_session_id=None,
        sender_surface=None,
        body=_notice_body(
            session_id=session_id,
            surface=str(row.get("executor_surface") or "desktop"),
            envelope_id=envelope_id,
        ),
        selector_snapshot={"actors": [str(actor_id)]},
        idempotency_key=notice_idempotency_key(
            envelope_id=envelope_id, session_id=session_id
        ),
        idempotency_intent_only=True,
        created_at=now,
        expires_at=now + timedelta(hours=policy.expiry_hours),
        recipients=[],
        actor_recipients=[
            ResolvedActorRecipient(
                actor_id=actor_id,
                label=actor_render_label(conn, actor_id),
                shared_org_ids=set(),
                resolution=[f"operator-of-session:{session_id}"],
            )
        ],
        wake_after_by_project={},
    )
    return str(details["message_id"]) if created else None


def notice_idempotency_key(*, envelope_id: str, session_id: str) -> str:
    """The dedupe key one waiting envelope's notice is recorded under."""
    return f"{NOTICE_IDEMPOTENCY_PREFIX}:{envelope_id}:{session_id}"


def _noticed_envelope(idempotency_key: str) -> tuple[str, str] | None:
    """The envelope and conversation one notice was raised for."""
    parts = str(idempotency_key).split(":")
    if len(parts) != 3 or parts[0] != NOTICE_IDEMPOTENCY_PREFIX:
        return None
    return parts[1], parts[2]


def _standing_notices(conn: Any, *, actor_id: int) -> list[dict[str, Any]]:
    """Notices still presented to one person, and nobody else's.

    Convergence happens where an Inbox is composed, so it is bounded by the
    Inbox being composed: the reader's own pending actor receipts. Sweeping
    every standing notice in the universe on a per-person read would make
    one person's page load do work on behalf of everyone.
    """
    marker = _p(conn)
    rows = conn.execute(
        "SELECT m.message_id AS message_id, "
        "m.idempotency_key AS idempotency_key FROM session_messages m "
        f"JOIN {ACTOR_RECIPIENT_TABLE} r ON r.message_id = m.message_id "
        f"WHERE m.cancelled_at IS NULL AND m.idempotency_key LIKE {marker} "
        f"AND r.recipient_kind = {marker} AND r.actor_id = {marker} "
        f"AND r.state = {marker}",
        (f"{NOTICE_IDEMPOTENCY_PREFIX}:%", ACTOR_KIND, int(actor_id), "pending"),
    ).fetchall()
    return [dict(row) for row in rows]


def _noticed_receipt(
    conn: Any,
    *,
    envelope_id: str,
    session_id: str,
) -> dict[str, Any] | None:
    marker = _p(conn)
    row = conn.execute(
        "SELECT r.state AS state, r.injection_count AS injection_count, "
        "r.executor_surface AS executor_surface, "
        "m.created_at AS message_created_at, m.cancelled_at AS cancelled_at, "
        "m.expires_at AS expires_at, hs.last_tool_call_at AS last_tool_call_at, "
        "hs.ended_at AS ended_at, hs.terminated_at AS terminated_at "
        "FROM session_message_recipients r "
        "JOIN session_messages m ON m.message_id = r.message_id "
        "LEFT JOIN harness_sessions hs ON hs.session_id = r.session_id "
        f"WHERE r.message_id = {marker} AND r.session_id = {marker}",
        (envelope_id, session_id),
    ).fetchone()
    return None if row is None else dict(row)


def _envelope_settled_reason(
    conn: Any,
    *,
    envelope_id: str,
    session_id: str,
    now: datetime,
) -> str | None:
    """Why the envelope behind one notice no longer needs a person."""
    receipt = _noticed_receipt(conn, envelope_id=envelope_id, session_id=session_id)
    if receipt is None:
        return "original_message_gone"
    if receipt.get("cancelled_at"):
        return "original_cancelled"
    expires = parse_timestamp(receipt.get("expires_at"))
    if expires is not None and expires <= now:
        return "original_expired"
    return wake_notice_settled_reason(receipt)


def settle_operator_wake_notices(
    conn: Any,
    *,
    actor_id: int,
    now: datetime | None = None,
) -> int:
    """Cancel this person's standing notices whose envelope needs no wake.

    Called wherever the Inbox is composed, for the same reason the ended
    decision sweep is: rendering is when a card that asks for nothing does
    its damage. Cancelling keeps the notice and its reason on record while
    taking it out of the Inbox, and it touches only the notices this module
    raised for ``actor_id`` -- another person's notice, and anyone's own
    waiting decision, are never dismissed here.
    """
    from yoke_core.domain.session_message_store import cancel_message_rows

    current = now or datetime.now(timezone.utc)
    settled = 0
    for notice in _standing_notices(conn, actor_id=actor_id):
        noticed = _noticed_envelope(notice["idempotency_key"])
        if noticed is None:
            continue
        envelope_id, session_id = noticed
        reason = _envelope_settled_reason(
            conn,
            envelope_id=envelope_id,
            session_id=session_id,
            now=current,
        )
        if reason is None:
            continue
        cancel_message_rows(
            conn,
            message_id=str(notice["message_id"]),
            actor_id=seed_system_actor(conn, SYSTEM_COMPONENT_YOKE_CORE),
            reason=reason,
            cancelled_at=current,
        )
        settled += 1
    if settled:
        conn.commit()
    return settled


__all__ = [
    "NOTICE_IDEMPOTENCY_PREFIX",
    "notice_idempotency_key",
    "notify_operator_to_wake",
    "operator_wake_notice_due",
    "settle_operator_wake_notices",
    "wake_notice_settled_reason",
]
