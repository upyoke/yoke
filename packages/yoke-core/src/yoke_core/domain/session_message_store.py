"""Durable message, recipient, and receipt mutations."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from yoke_core.domain.db_helpers import instant_parameter

from yoke_core.domain import db_backend
from yoke_core.domain.actor_message_recipients import (
    ResolvedActorRecipient,
    expire_actor_recipients_for_cancel,
    insert_actor_recipient_rows,
)
from yoke_core.domain.session_message_recipient_rows import insert_session_receipt
from yoke_core.domain.session_message_launch_queue import message_intent_json
from yoke_core.domain.session_message_reads import (
    message_details,
    public_recipients,
)
from yoke_core.domain.session_message_types import (
    ResolvedRecipient,
    SessionMessageError,
)
from yoke_core.domain.session_message_recipient_scope import owner_key


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def body_sha256(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def begin_message_mutation(conn: Any) -> None:
    if not db_backend.connection_is_postgres(conn) and not bool(
        getattr(conn, "in_transaction", False)
    ):
        conn.execute("BEGIN IMMEDIATE")


def idempotent_message(
    conn: Any, *, sender_actor_id: int | None, idempotency_key: str
) -> dict[str, Any] | None:
    from yoke_core.domain.deployment_qa_reported_results import reusable_qa_notice
    marker = _p(conn)
    engine = sender_actor_id is None
    row = conn.execute(
        "SELECT message_id FROM session_messages WHERE sender_actor_id "
        + ("IS NULL" if engine else f"={marker}")
        + f" AND idempotency_key={marker} AND cancelled_at IS NULL",
        (idempotency_key,) if engine else (sender_actor_id, idempotency_key),
    ).fetchone()
    return reusable_qa_notice(conn, message_details(conn, str(row[0])) if row else None)


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
    stored = message_intent_json(existing["selector_snapshot"])
    if existing["body_sha256"] != digest or stored != message_intent_json(
        json.loads(selector_json)
    ):
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
    sender_actor_id: int | None,
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
    wake_after_by_owner: dict[tuple[str, int], datetime],
) -> tuple[dict[str, Any], bool]:
    """Insert one immutable message snapshot, or return its exact dedupe."""
    selector_json = json.dumps(selector_snapshot, sort_keys=True, separators=(",", ":"))
    digest = body_sha256(body)
    if idempotency_key:
        existing = idempotent_message(
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
            instant_parameter(conn, created_at),
            instant_parameter(conn, expires_at),
            sender_surface,
        ),
    )
    if not inserted.rowcount:
        if not idempotency_key:
            raise SessionMessageError("message_conflict", "message id collision")
        existing = idempotent_message(
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
    for recipient in recipients:
        insert_session_receipt(
            conn,
            message_id=message_id,
            recipient=recipient,
            created_at=created_at,
            wake_after=wake_after_by_owner[owner_key(recipient.routing_snapshot())],
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
            instant_parameter(conn, acknowledged_at),
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
    """Close a recipient's open envelopes and attempts, naming the absence.

    This only mutates envelopes and attempts; it does not notify senders.
    Callers own any sender notice after commit. The result_code records the
    cause on open attempts, not on recipient rows.
    """
    marker = _p(conn)
    stamp = instant_parameter(conn, cancelled_at)
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
    actor_id: int | None,
    reason: str,
    cancelled_at: datetime,
) -> dict[str, Any]:
    details = message_details(conn, message_id)
    if details.get("cancelled_at"):
        return details
    cancel_messages(
        conn,
        message_ids=[message_id],
        actor_id=actor_id,
        reason=reason,
        cancelled_at=cancelled_at,
    )
    return message_details(conn, message_id)


def cancel_messages(
    conn: Any,
    *,
    message_ids: list[str],
    actor_id: int | None,
    reason: str,
    cancelled_at: datetime,
) -> None:
    """Cancel every still-open message in *message_ids* with one statement per table."""
    if not message_ids:
        return
    marker = _p(conn)
    stamp = instant_parameter(conn, cancelled_at)
    rows = conn.execute(
        "UPDATE session_messages SET cancelled_at=" + marker + ", "
        "cancelled_by_actor_id=" + marker + ", cancellation_reason=" + marker + " "
        f"WHERE message_id IN ({','.join(marker for _ in message_ids)}) "
        "AND cancelled_at IS NULL RETURNING message_id",
        (stamp, actor_id, reason, *message_ids),
    ).fetchall()
    # A message cancelled earlier keeps its recipients' recorded outcome.
    message_ids = [str(row[0]) for row in rows]
    if not message_ids:
        return
    ids = ",".join(marker for _ in message_ids)
    conn.execute(
        "UPDATE session_message_recipients SET state='cancelled', "
        f"cancelled_at={marker}, injection_lease_id=NULL, "
        "injection_leased_at=NULL, injection_lease_expires_at=NULL "
        f"WHERE message_id IN ({ids}) AND state IN ('pending','injected')",
        (stamp, *message_ids),
    )
    expire_actor_recipients_for_cancel(
        conn, message_ids=message_ids, expired_at=cancelled_at
    )


__all__ = [
    "acknowledge_recipient",
    "begin_message_mutation",
    "body_sha256",
    "cancel_message_rows",
    "cancel_messages",
    "cancel_open_recipients",
    "idempotent_message",
    "insert_message",
    "message_details",
    "public_recipients",
]
