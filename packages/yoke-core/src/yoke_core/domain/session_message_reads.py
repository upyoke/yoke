"""Read projections over Fleet messages and both recipient lifecycles."""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.session_control.sender_surface import sender_surface_label
from yoke_core.domain import db_backend
from yoke_core.domain.actor_message_recipients import (
    actor_recipients_for_message,
)
from yoke_core.domain.actor_render import actor_render_label
from yoke_core.domain.session_message_types import (
    SessionMessageError,
    row_dict,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _decode(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return fallback


def sender_identity_projection(
    conn: Any,
    actor_id: int,
    *,
    sender_surface: str | None = None,
) -> dict[str, Any]:
    marker = _p(conn)
    row = conn.execute(
        f"SELECT kind FROM actors WHERE id={marker}", (actor_id,)
    ).fetchone()
    projection = {
        "sender_actor_label": actor_render_label(conn, actor_id),
        "sender_actor_kind": str(row[0]) if row is not None else None,
    }
    if sender_surface is not None:
        projection["sender_surface_label"] = sender_surface_label(sender_surface)
    return projection


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
    message["actor_recipients"] = actor_recipients_for_message(conn, message_id)
    message.update(
        sender_identity_projection(
            conn,
            int(message["sender_actor_id"]),
            sender_surface=message.get("sender_surface"),
        )
    )
    message.update(message_attempt_evidence(conn, message_id))
    return message


_UNACKNOWLEDGED_STATES: tuple[str, ...] = ("pending", "injected")


def _session_state_clause(marker: str, state: str | None) -> tuple[str, list[Any]]:
    if state == "unacknowledged":
        slots = ",".join(marker for _ in _UNACKNOWLEDGED_STATES)
        return f"r.state IN ({slots})", list(_UNACKNOWLEDGED_STATES)
    if state is not None:
        return f"r.state={marker}", [state]
    return "1=1", []


def _actor_state_clause(marker: str, state: str | None) -> tuple[str, list[Any]]:
    mapped = {"unacknowledged": "pending", "acknowledged": "read"}.get(
        str(state), state
    )
    if mapped == "cancelled":
        return "1=0", []
    if mapped is not None:
        return f"ar.state={marker}", [mapped]
    return "1=1", []


def list_message_ids(
    conn: Any,
    *,
    state: str | None,
    session_id: str | None,
    actor_id: int,
    limit: int,
) -> list[str]:
    marker = _p(conn)
    session_state, session_params = _session_state_clause(marker, state)
    session_filter = ""
    if session_id is not None:
        session_filter = f" AND r.session_id={marker}"
        session_params.append(session_id)
    actor_state, actor_params = _actor_state_clause(marker, state)
    actor_branch = "1=0"
    if session_id is None:
        actor_branch = (
            "EXISTS (SELECT 1 FROM actor_message_recipients ar "
            "WHERE ar.message_id=m.message_id AND "
            f"(ar.actor_id={marker} OR m.sender_actor_id={marker}) AND {actor_state})"
        )
        actor_params = [actor_id, actor_id, *actor_params]
    else:
        actor_params = []
    params = [*session_params, *actor_params, max(1, min(int(limit), 500))]
    rows = conn.execute(
        "SELECT m.message_id,m.created_at FROM session_messages m WHERE "
        "EXISTS (SELECT 1 FROM session_message_recipients r WHERE "
        f"r.message_id=m.message_id AND {session_state}{session_filter}) OR "
        + actor_branch
        + " ORDER BY m.created_at DESC,m.message_id LIMIT "
        + marker,
        tuple(params),
    ).fetchall()
    return [str(row[0]) for row in rows]


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
    "list_message_ids",
    "message_details",
    "public_recipients",
    "recipient_project_ids",
    "sender_identity_projection",
]
