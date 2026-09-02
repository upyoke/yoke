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
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping

from yoke_contracts.session_control.capabilities import native_wake_supported
from yoke_core.domain import db_backend
from yoke_core.domain.actor_message_recipients import ResolvedActorRecipient
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


def operator_wake_notice_due(
    row: Mapping[str, Any],
    *,
    grace_seconds: int,
    now: datetime,
) -> bool:
    """Whether this receipt is a desktop message its operator has not seen.

    The three facts are the surface's declared wake authority, the same
    "no hook has run since the send" evidence a native escalation reads,
    and the same grace window it waits out. A session that has ended is
    excluded: there is no window left for anyone to type into.
    """
    if native_wake_supported(str(row.get("executor_surface") or "")):
        return False
    if row.get("ended_at") or row.get("terminated_at"):
        return False
    if not undelivered_since_send(row, now=now):
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
        idempotency_key=f"{NOTICE_IDEMPOTENCY_PREFIX}:{envelope_id}:{session_id}",
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


__all__ = [
    "NOTICE_IDEMPOTENCY_PREFIX",
    "notify_operator_to_wake",
    "operator_wake_notice_due",
]
