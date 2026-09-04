"""Durable message, recipient, and receipt mutations."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.actor_message_recipients import (
    ResolvedActorRecipient,
    expire_actor_recipients_for_cancel,
    insert_actor_recipient_rows,
)
from yoke_core.domain.session_message_reads import (
    list_message_ids,
    message_details,
    public_recipients,
    recipient_project_ids,
)
from yoke_core.domain.session_message_types import (
    ResolvedRecipient,
    SessionMessageError,
    timestamp,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def body_sha256(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def begin_message_mutation(conn: Any) -> None:
    if not db_backend.connection_is_postgres(conn) and not bool(
        getattr(conn, "in_transaction", False)
    ):
        conn.execute("BEGIN IMMEDIATE")


def _idempotent_message(
    conn: Any, *, sender_actor_id: int, idempotency_key: str
) -> dict[str, Any] | None:
    marker = _p(conn)
    row = conn.execute(
        "SELECT message_id FROM session_messages "
        f"WHERE sender_actor_id={marker} AND idempotency_key={marker}",
        (sender_actor_id, idempotency_key),
    ).fetchone()
    return message_details(conn, str(row[0])) if row else None


def _same_intent(
    existing: dict[str, Any],
    *,
    digest: str,
    selector_json: str,
    intent_only: bool,
) -> dict[str, Any]:
    """Return the existing message, or refuse a key reused for other intent.

    ``intent_only`` is what a DERIVED key means: the caller composed the key
    from the intent itself -- for example, a session's terminal report or a
    machinery notice keyed by its durable subject -- so a reworded retry or
    a second route carrying the same notice is not a conflict.
    """
    if intent_only:
        return existing
    stored = json.dumps(
        existing["selector_snapshot"], sort_keys=True, separators=(",", ":")
    )
    if existing["body_sha256"] != digest or stored != selector_json:
        raise SessionMessageError(
            "idempotency_conflict",
            "idempotency key already names a different message intent",
            jsonpath="$.payload.idempotency_key",
        )
    return existing


def insert_message(
    conn: Any,
    *,
    message_id: str | None = None,
    sender_actor_id: int,
    sender_session_id: str | None,
    sender_surface: str | None,
    body: str,
    selector_snapshot: dict[str, Any],
    idempotency_key: str | None,
    idempotency_intent_only: bool = False,
    created_at: datetime,
    expires_at: datetime,
    recipients: list[ResolvedRecipient],
    actor_recipients: list[ResolvedActorRecipient],
    wake_after_by_project: dict[int, datetime],
) -> tuple[dict[str, Any], bool]:
    """Insert one immutable message snapshot, or return its exact dedupe."""
    selector_json = json.dumps(selector_snapshot, sort_keys=True, separators=(",", ":"))
    digest = body_sha256(body)
    if idempotency_key:
        existing = _idempotent_message(
            conn,
            sender_actor_id=sender_actor_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            return (
                _same_intent(
                    existing,
                    digest=digest,
                    selector_json=selector_json,
                    intent_only=idempotency_intent_only,
                ),
                False,
            )
    marker = _p(conn)
    message_id = message_id or str(uuid.uuid4())
    inserted = conn.execute(
        "INSERT INTO session_messages (message_id, sender_actor_id, "
        "sender_session_id, body, body_sha256, selector_snapshot, "
        "idempotency_key, created_at, expires_at, sender_surface) "
        "VALUES (" + ", ".join(marker for _ in range(10)) + ") "
        "ON CONFLICT DO NOTHING",
        (
            message_id,
            sender_actor_id,
            sender_session_id,
            body,
            digest,
            selector_json,
            idempotency_key,
            timestamp(created_at),
            timestamp(expires_at),
            sender_surface,
        ),
    )
    if not inserted.rowcount:
        if not idempotency_key:
            raise SessionMessageError("message_conflict", "message id collision")
        existing = _idempotent_message(
            conn,
            sender_actor_id=sender_actor_id,
            idempotency_key=idempotency_key,
        )
        if existing is None:
            raise SessionMessageError("message_conflict", "message insert conflicted")
        return (
            _same_intent(
                existing,
                digest=digest,
                selector_json=selector_json,
                intent_only=idempotency_intent_only,
            ),
            False,
        )
    created_stamp = timestamp(created_at)
    for recipient in recipients:
        conn.execute(
            "INSERT INTO session_message_recipients (message_id, session_id, "
            "project_id, resolution_evidence, routing_snapshot, executor_surface, "
            "executor_version, machine_id, state, created_at, wake_after) "
            f"VALUES ({', '.join(marker for _ in range(11))})",
            (
                message_id,
                recipient.session_id,
                recipient.project_id,
                json.dumps(sorted(set(recipient.resolution))),
                json.dumps(recipient.routing_snapshot(), sort_keys=True),
                recipient.executor_surface,
                recipient.executor_version,
                recipient.machine_id,
                "pending",
                created_stamp,
                timestamp(wake_after_by_project[recipient.project_id]),
            ),
        )
    insert_actor_recipient_rows(
        conn,
        message_id=message_id,
        recipients=actor_recipients,
        created_at=created_at,
    )
    return message_details(conn, message_id), True


_UNACKNOWLEDGED_STATES: tuple[str, ...] = ("pending", "injected")


def acknowledge_recipient(
    conn: Any,
    *,
    message_id: str,
    session_id: str,
    acknowledged_at: datetime,
) -> dict[str, Any]:
    begin_message_mutation(conn)
    marker = _p(conn)
    lock = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    row = conn.execute(
        "SELECT state FROM session_message_recipients "
        f"WHERE message_id={marker} AND session_id={marker}" + lock,
        (message_id, session_id),
    ).fetchone()
    if row is None:
        exists = conn.execute(
            f"SELECT 1 FROM session_messages WHERE message_id={marker}",
            (message_id,),
        ).fetchone()
        code = "acknowledge_self_only" if exists else "message_not_found"
        raise SessionMessageError(code, "only the recipient session may acknowledge")
    state = str(row[0])
    if state == "acknowledged":
        return message_details(conn, message_id)
    # A recipient acknowledging its own receipt is the strongest possible
    # evidence of delivery, so `pending` is accepted alongside `injected`.
    # A native wake names the message id without carrying its body, and the
    # session that follows that instruction can reach the acknowledgement
    # before any hook event has flipped the row to `injected` — refusing
    # there would deny receipt of a message the sender can see was received.
    # Terminal states stay refused: expired and cancelled receipts are over.
    if state not in _UNACKNOWLEDGED_STATES:
        raise SessionMessageError(
            "invalid_state", f"recipient state {state!r} cannot be acknowledged"
        )
    slots = ",".join(marker for _ in _UNACKNOWLEDGED_STATES)
    cursor = conn.execute(
        "UPDATE session_message_recipients SET state='acknowledged', "
        f"acknowledged_at={marker}, injection_lease_id=NULL, "
        "injection_leased_at=NULL, injection_lease_expires_at=NULL "
        f"WHERE message_id={marker} AND session_id={marker} "
        f"AND state IN ({slots})",
        (
            timestamp(acknowledged_at),
            message_id,
            session_id,
            *_UNACKNOWLEDGED_STATES,
        ),
    )
    if cursor.rowcount != 1:
        raise SessionMessageError(
            "invalid_state", "recipient state changed before acknowledgment"
        )
    return message_details(conn, message_id)


def cancel_open_recipients(
    conn: Any,
    *,
    session_id: str,
    cancelled_at: datetime,
    result_code: str,
) -> int:
    """Silence one recipient's open envelopes and close their attempts.

    A recipient that can no longer take delivery leaves its senders waiting
    on an answer that is never coming, so the envelopes are cancelled rather
    than left pending: the sender reads ``cancelled`` on its own message and
    ``result_code`` says which absence closed it. Deliberate termination and
    a relay's verified-dead process both end that way, and they name
    themselves through *result_code* rather than through two copies of this
    statement pair drifting apart.
    """
    marker = _p(conn)
    stamp = timestamp(cancelled_at)
    row = conn.execute(
        "SELECT COUNT(*) FROM session_message_recipients "
        f"WHERE session_id = {marker} AND state IN ('pending','injected')",
        (session_id,),
    ).fetchone()
    count = int(row[0]) if row is not None else 0
    conn.execute(
        "UPDATE session_message_recipients SET state='cancelled',cancelled_at="
        f"{marker},injection_lease_id=NULL,injection_leased_at=NULL,"
        f"injection_lease_expires_at=NULL WHERE session_id={marker} "
        "AND state IN ('pending','injected')",
        (stamp, session_id),
    )
    conn.execute(
        f"UPDATE session_message_attempts SET completed_at={marker},"
        f"result_code={marker} WHERE target_session_id={marker} "
        "AND completed_at IS NULL",
        (stamp, result_code, session_id),
    )
    return count


def cancel_message_rows(
    conn: Any,
    *,
    message_id: str,
    actor_id: int,
    reason: str,
    cancelled_at: datetime,
) -> dict[str, Any]:
    marker = _p(conn)
    details = message_details(conn, message_id)
    if details.get("cancelled_at"):
        return details
    stamp = timestamp(cancelled_at)
    conn.execute(
        "UPDATE session_messages SET cancelled_at=" + marker + ", "
        "cancelled_by_actor_id=" + marker + ", cancellation_reason=" + marker + " "
        "WHERE message_id=" + marker,
        (stamp, actor_id, reason, message_id),
    )
    conn.execute(
        "UPDATE session_message_recipients SET state='cancelled', "
        f"cancelled_at={marker}, injection_lease_id=NULL, "
        "injection_leased_at=NULL, injection_lease_expires_at=NULL "
        f"WHERE message_id={marker} AND state IN ('pending','injected')",
        (stamp, message_id),
    )
    expire_actor_recipients_for_cancel(
        conn, message_id=message_id, expired_at=cancelled_at
    )
    return message_details(conn, message_id)


__all__ = [
    "acknowledge_recipient",
    "begin_message_mutation",
    "body_sha256",
    "cancel_message_rows",
    "cancel_open_recipients",
    "insert_message",
    "list_message_ids",
    "message_details",
    "public_recipients",
    "recipient_project_ids",
]
