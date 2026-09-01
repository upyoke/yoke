"""Human-recipient resolution and read-state storage for Fleet messages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from yoke_contracts.session_control.models import RecipientSelector
from yoke_core.domain import db_backend
from yoke_core.domain.actor_render import actor_render_label
from yoke_core.domain.actors import resolve_actor_by_label, validate_actor_id
from yoke_core.domain.organization_settings import read_organization_setting
from yoke_core.domain.session_message_types import (
    SessionMessageError,
    row_dict,
    timestamp,
    utc_now,
)


@dataclass
class ResolvedActorRecipient:
    """One deduplicated human member plus shared organization authority."""

    actor_id: int
    label: str | None
    shared_org_ids: set[int]
    resolution: list[str] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "label": self.label,
            "kind": "human",
            "resolution": sorted(set(self.resolution)),
        }


@dataclass(frozen=True)
class ActorMessageLimits:
    expiry_hours: int
    max_body_bytes: int


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _org_ids(conn: Any, actor_id: int) -> set[int]:
    marker = _p(conn)
    rows = conn.execute(
        f"SELECT DISTINCT org_id FROM actor_org_roles WHERE actor_id={marker}",
        (actor_id,),
    ).fetchall()
    return {int(row[0]) for row in rows}


def _resolve_actor_ref(conn: Any, raw: str) -> int:
    cleaned = str(raw or "").strip()
    actor_id = (
        int(cleaned) if cleaned.isdigit() else resolve_actor_by_label(conn, cleaned)
    )
    if actor_id is None or not validate_actor_id(conn, int(actor_id)):
        raise SessionMessageError(
            "actor_recipient_not_found",
            f"actor anchor {raw!r} did not resolve; use an exact member actor id "
            "or registered resolution label",
            jsonpath="$.payload.selector.actors",
        )
    return int(actor_id)


def resolve_actor_recipients(
    conn: Any,
    selector: RecipientSelector,
    *,
    sender_actor_id: int,
) -> list[ResolvedActorRecipient]:
    """Resolve actor anchors to human members sharing the sender's org."""
    if not selector.actors:
        return []
    sender_org_ids = _org_ids(conn, sender_actor_id)
    if not sender_org_ids:
        raise SessionMessageError(
            "sender_not_org_member",
            f"actor {sender_actor_id} has no organization membership; grant an "
            "organization role before addressing human members",
        )
    resolved: dict[int, ResolvedActorRecipient] = {}
    marker = _p(conn)
    for raw in selector.actors:
        actor_id = _resolve_actor_ref(conn, raw)
        row = conn.execute(
            f"SELECT kind FROM actors WHERE id={marker}", (actor_id,)
        ).fetchone()
        if row is None or str(row[0]) != "human":
            raise SessionMessageError(
                "actor_recipient_not_human",
                f"actor anchor {raw!r} does not name a human organization member",
                jsonpath="$.payload.selector.actors",
            )
        shared = sender_org_ids & _org_ids(conn, actor_id)
        if not shared:
            raise SessionMessageError(
                "actor_recipient_forbidden",
                f"actor anchor {raw!r} is not a member of the sender's organization",
                jsonpath="$.payload.selector.actors",
            )
        recipient = resolved.setdefault(
            actor_id,
            ResolvedActorRecipient(
                actor_id=actor_id,
                label=actor_render_label(conn, actor_id),
                shared_org_ids=set(),
            ),
        )
        recipient.shared_org_ids.update(shared)
        recipient.resolution.append(f"actor:{raw}")
    return [resolved[key] for key in sorted(resolved)]


def actor_message_limits(
    conn: Any, recipients: list[ResolvedActorRecipient]
) -> ActorMessageLimits | None:
    org_ids = sorted(
        {org_id for recipient in recipients for org_id in recipient.shared_org_ids}
    )
    if not org_ids:
        return None
    expiries = [
        int(read_organization_setting(conn, org_id, "fleet.message_expiry_hours")[0])
        for org_id in org_ids
    ]
    body_limits = [
        int(read_organization_setting(conn, org_id, "fleet.max_body_bytes")[0])
        for org_id in org_ids
    ]
    return ActorMessageLimits(
        expiry_hours=min(expiries), max_body_bytes=min(body_limits)
    )


def insert_actor_recipient_rows(
    conn: Any,
    *,
    message_id: str,
    recipients: list[ResolvedActorRecipient],
    created_at: datetime,
) -> None:
    marker = _p(conn)
    stamp = timestamp(created_at)
    for recipient in recipients:
        conn.execute(
            "INSERT INTO actor_message_recipients "
            "(message_id,actor_id,state,created_at) "
            f"VALUES ({marker},{marker},'pending',{marker})",
            (message_id, recipient.actor_id, stamp),
        )


def actor_recipients_for_message(conn: Any, message_id: str) -> list[dict[str, Any]]:
    marker = _p(conn)
    rows = conn.execute(
        "SELECT actor_id,state,created_at,read_at,expired_at "
        f"FROM actor_message_recipients WHERE message_id={marker} ORDER BY actor_id",
        (message_id,),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        recipient = row_dict(row)
        actor_id = int(recipient["actor_id"])
        recipient.update({"label": actor_render_label(conn, actor_id), "kind": "human"})
        result.append(recipient)
    return result


def expire_due_actor_recipients(conn: Any, *, now: datetime | None = None) -> int:
    marker = _p(conn)
    stamp = timestamp(now or utc_now())
    cursor = conn.execute(
        "UPDATE actor_message_recipients SET state='expired',expired_at="
        + marker
        + " WHERE state='pending' AND EXISTS (SELECT 1 FROM session_messages m "
        "WHERE m.message_id=actor_message_recipients.message_id AND "
        f"(m.cancelled_at IS NOT NULL OR m.expires_at<={marker}))",
        (stamp, stamp),
    )
    return int(cursor.rowcount)


def acknowledge_actor_recipient(
    conn: Any,
    *,
    message_id: str,
    actor_id: int,
    read_at: datetime | None = None,
) -> None:
    from yoke_core.domain.session_message_store import begin_message_mutation

    begin_message_mutation(conn)
    expire_due_actor_recipients(conn, now=read_at)
    marker = _p(conn)
    lock = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    row = conn.execute(
        "SELECT state FROM actor_message_recipients "
        f"WHERE message_id={marker} AND actor_id={marker}" + lock,
        (message_id, actor_id),
    ).fetchone()
    if row is None:
        exists = conn.execute(
            f"SELECT 1 FROM session_messages WHERE message_id={marker}",
            (message_id,),
        ).fetchone()
        code = "actor_acknowledge_self_only" if exists else "message_not_found"
        raise SessionMessageError(
            code, "only an addressed actor may acknowledge this message"
        )
    state = str(row[0])
    if state == "read":
        return
    if state != "pending":
        raise SessionMessageError(
            "invalid_state", f"actor recipient state {state!r} cannot be acknowledged"
        )
    cursor = conn.execute(
        "UPDATE actor_message_recipients SET state='read',read_at="
        + marker
        + f" WHERE message_id={marker} AND actor_id={marker} AND state='pending'",
        (timestamp(read_at or utc_now()), message_id, actor_id),
    )
    if cursor.rowcount != 1:
        raise SessionMessageError(
            "invalid_state", "actor recipient state changed before acknowledgment"
        )


def expire_actor_recipients_for_cancel(
    conn: Any, *, message_id: str, expired_at: datetime
) -> None:
    marker = _p(conn)
    conn.execute(
        "UPDATE actor_message_recipients SET state='expired',expired_at="
        + marker
        + f" WHERE message_id={marker} AND state='pending'",
        (timestamp(expired_at), message_id),
    )


def actor_message_ids(
    conn: Any, *, actor_id: int, state: str | None, limit: int
) -> list[str]:
    marker = _p(conn)
    mapped = {"unacknowledged": "pending", "acknowledged": "read"}.get(
        str(state), state
    )
    clauses = [f"r.actor_id={marker}"]
    params: list[Any] = [actor_id]
    if mapped == "cancelled":
        return []
    if mapped is not None:
        clauses.append(f"r.state={marker}")
        params.append(mapped)
    params.append(max(1, min(int(limit), 500)))
    rows = conn.execute(
        "SELECT m.message_id FROM actor_message_recipients r "
        "JOIN session_messages m ON m.message_id=r.message_id WHERE "
        + " AND ".join(clauses)
        + f" AND m.cancelled_at IS NULL AND m.expires_at>{marker}"
        + " ORDER BY m.created_at DESC,m.message_id LIMIT "
        + marker,
        tuple([*params[:-1], timestamp(utc_now()), params[-1]]),
    ).fetchall()
    return [str(row[0]) for row in rows]


def inbox_actor_messages(
    conn: Any, *, actor_id: int, include_read: bool
) -> dict[str, Any]:
    ids = actor_message_ids(
        conn,
        actor_id=actor_id,
        state=None if include_read else "pending",
        limit=100,
    )
    from yoke_core.domain.session_message_reads import message_details

    messages = []
    for message_id in ids:
        message = message_details(conn, message_id)
        receipt = next(
            row
            for row in message["actor_recipients"]
            if int(row["actor_id"]) == actor_id
        )
        message["actor_receipt"] = receipt
        messages.append(message)
    return {
        "messages": messages,
        "pending_count": sum(
            row["actor_receipt"]["state"] == "pending" for row in messages
        ),
    }


__all__ = [
    "ActorMessageLimits",
    "ResolvedActorRecipient",
    "acknowledge_actor_recipient",
    "actor_message_ids",
    "actor_message_limits",
    "actor_recipients_for_message",
    "expire_actor_recipients_for_cancel",
    "expire_due_actor_recipients",
    "inbox_actor_messages",
    "insert_actor_recipient_rows",
    "resolve_actor_recipients",
]
