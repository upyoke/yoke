"""Durable message, recipient, and receipt mutations."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.session_message_types import (
    ResolvedRecipient,
    SessionMessageError,
    row_dict,
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


def _decode(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return fallback


def message_details(conn: Any, message_id: str) -> dict[str, Any]:
    from yoke_core.domain.session_message_attempt_reads import (
        message_attempt_evidence,
    )

    marker = _p(conn)
    row = conn.execute(
        f"SELECT * FROM session_messages WHERE message_id={marker}",
        (message_id,),
    ).fetchone()
    if row is None:
        raise SessionMessageError(
            "message_not_found", f"message {message_id!r} not found"
        )
    message = row_dict(row)
    recipients = [
        row_dict(value)
        for value in conn.execute(
            "SELECT * FROM session_message_recipients "
            f"WHERE message_id={marker} ORDER BY session_id",
            (message_id,),
        ).fetchall()
    ]
    message["selector_snapshot"] = _decode(message["selector_snapshot"], {})
    for recipient in recipients:
        recipient["resolution_evidence"] = _decode(recipient["resolution_evidence"], [])
        recipient["routing_snapshot"] = _decode(recipient["routing_snapshot"], {})
    message["recipients"] = recipients
    message.update(message_attempt_evidence(conn, message_id))
    return message


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


def insert_message(
    conn: Any,
    *,
    message_id: str | None = None,
    sender_actor_id: int,
    sender_session_id: str | None,
    body: str,
    selector_snapshot: dict[str, Any],
    idempotency_key: str | None,
    created_at: datetime,
    expires_at: datetime,
    recipients: list[ResolvedRecipient],
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
            if (
                existing["body_sha256"] != digest
                or json.dumps(
                    existing["selector_snapshot"], sort_keys=True, separators=(",", ":")
                )
                != selector_json
            ):
                raise SessionMessageError(
                    "idempotency_conflict",
                    "idempotency key already names a different message intent",
                    jsonpath="$.payload.idempotency_key",
                )
            return existing, False
    marker = _p(conn)
    message_id = message_id or str(uuid.uuid4())
    inserted = conn.execute(
        "INSERT INTO session_messages (message_id, sender_actor_id, "
        "sender_session_id, body, body_sha256, selector_snapshot, "
        "idempotency_key, created_at, expires_at) "
        f"VALUES ({', '.join(marker for _ in range(9))}) ON CONFLICT DO NOTHING",
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
        if (
            existing["body_sha256"] != digest
            or json.dumps(
                existing["selector_snapshot"],
                sort_keys=True,
                separators=(",", ":"),
            )
            != selector_json
        ):
            raise SessionMessageError(
                "idempotency_conflict",
                "idempotency key already names a different message intent",
            )
        return existing, False
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
    return message_details(conn, message_id), True


def list_message_ids(
    conn: Any,
    *,
    state: str | None,
    session_id: str | None,
    limit: int,
) -> list[str]:
    marker = _p(conn)
    clauses: list[str] = []
    params: list[Any] = []
    if state is not None:
        clauses.append(f"r.state={marker}")
        params.append(state)
    if session_id is not None:
        clauses.append(f"r.session_id={marker}")
        params.append(session_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, min(int(limit), 500)))
    rows = conn.execute(
        "SELECT DISTINCT m.message_id, m.created_at FROM session_messages m "
        f"JOIN session_message_recipients r ON r.message_id=m.message_id {where} "
        f"ORDER BY m.created_at DESC, m.message_id LIMIT {marker}",
        tuple(params),
    ).fetchall()
    return [str(row[0]) for row in rows]


# Receipt states a session may acknowledge from. Ordered so the SQL
# placeholder tuple stays stable across calls.
_ACKNOWLEDGEABLE_STATES: tuple[str, ...] = ("pending", "injected")


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
    if state not in _ACKNOWLEDGEABLE_STATES:
        raise SessionMessageError(
            "invalid_state", f"recipient state {state!r} cannot be acknowledged"
        )
    slots = ",".join(marker for _ in _ACKNOWLEDGEABLE_STATES)
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
            *_ACKNOWLEDGEABLE_STATES,
        ),
    )
    if cursor.rowcount != 1:
        raise SessionMessageError(
            "invalid_state", "recipient state changed before acknowledgment"
        )
    return message_details(conn, message_id)


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
    return message_details(conn, message_id)


def recipient_project_ids(details: dict[str, Any]) -> set[int]:
    return {int(row["project_id"]) for row in details.get("recipients", [])}


def public_recipients(details: dict[str, Any]) -> list[dict[str, Any]]:
    public_keys = (
        "session_id",
        "project",
        "executor",
        "executor_surface",
        "machine_id",
        "liveness",
        "messageability",
        "resolution",
    )
    recipients: list[dict[str, Any]] = []
    for row in details.get("recipients", []):
        snapshot = row.get("routing_snapshot")
        recipients.append(
            {key: snapshot.get(key) for key in public_keys}
            if isinstance(snapshot, dict)
            else {}
        )
    return recipients


__all__ = [
    "acknowledge_recipient",
    "begin_message_mutation",
    "body_sha256",
    "cancel_message_rows",
    "insert_message",
    "list_message_ids",
    "message_details",
    "public_recipients",
    "recipient_project_ids",
]
