"""Read projections over Fleet messages and every recipient lifecycle."""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.timestamps import temporal_wire
from yoke_contracts.session_control.sender_surface import sender_surface_label
from yoke_core.domain import db_backend
from yoke_core.domain.actor_message_recipients import (
    ACTOR_KIND,
    actor_recipients_for_message,
)
from yoke_core.domain.actor_render import render_actor_name
from yoke_core.domain.session_message_receipt_expiry import (
    OPEN_SESSION_STATES,
    STEERING_OPEN_STATES,
    actor_state_sql,
    session_state_sql,
    steering_open_sql,
    steering_settled_sql,
)
from yoke_core.domain.session_message_launch_queue import (
    project_launch_mail,
    queued_message_clause,
)
from yoke_core.domain.session_message_types import (
    SessionMessageError,
    row_dict,
)
from yoke_core.domain.steering_message_recipients import (
    STATE_ACKNOWLEDGED,
    STATE_AWAITING_SEAT,
    STATE_DELIVERED,
    STEERING_KIND,
)
from yoke_core.domain.steering_recipient_projection import (
    stored_steering_recipient,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _decode(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return fallback


#: How every surface names the sender of a message the engine itself sent,
#: which is stored with no sender actor.
ENGINE_SENDER_LABEL = "Yoke"


def sender_identity_projection(
    conn: Any,
    actor_id: int | None,
    *,
    sender_surface: str | None = None,
) -> dict[str, Any]:
    if actor_id is None:
        projection: dict[str, Any] = {
            "sender_actor_label": ENGINE_SENDER_LABEL,
            "sender_actor_kind": None,
        }
    else:
        row = conn.execute(
            f"SELECT kind FROM actors WHERE id={_p(conn)}", (actor_id,)
        ).fetchone()
        projection = {
            "sender_actor_label": render_actor_name(conn, actor_id),
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
    message.update(project_launch_mail(conn, message))
    message["actor_recipients"] = actor_recipients_for_message(conn, message_id)
    steering = stored_steering_recipient(conn, message_id)
    if steering is not None:
        message["steering_recipient"] = steering
    message.update(
        sender_identity_projection(
            conn,
            message["sender_actor_id"],
            sender_surface=message.get("sender_surface"),
        )
    )
    message.update(message_attempt_evidence(conn, message_id))
    return temporal_wire(message)


def _session_state_clause(
    marker: str, state: str | None, now: Any
) -> tuple[str, list[Any]]:
    if state == "unacknowledged":
        return session_state_sql(marker, OPEN_SESSION_STATES, now)
    if state is not None:
        return session_state_sql(marker, (state,), now)
    return "1=1", []


def _actor_state_clause(
    marker: str, state: str | None, now: Any
) -> tuple[str, list[Any]]:
    mapped = {"unacknowledged": "pending", "acknowledged": "read"}.get(
        str(state), state
    )
    if mapped == "cancelled":
        return "1=0", []
    if mapped is not None:
        return actor_state_sql(marker, mapped, now)
    return "1=1", []


#: How a session-recipient state filter reads against a role-addressed row.
#: A steering row is unacknowledged while it is parked or sitting with a
#: seat and its message is still open, settled once that seat acknowledges
#: it, and expired once its message is cancelled or past expiry -- the one
#: rule in :mod:`yoke_core.domain.session_message_receipt_expiry`. The
#: delivery-mechanics states have no counterpart on a role address at all.
_STEERING_OPEN_BY_FILTER: dict[str, tuple[str, ...]] = {
    "unacknowledged": STEERING_OPEN_STATES,
    "pending": (STATE_AWAITING_SEAT,),
    "injected": (STATE_DELIVERED,),
}


def _steering_state_clause(
    marker: str, state: str | None, now: Any
) -> tuple[str, list[Any]]:
    if state is None:
        return "1=1", []
    if state == STATE_ACKNOWLEDGED:
        return f"sr.state={marker}", [STATE_ACKNOWLEDGED]
    if state == "expired":
        states = STEERING_OPEN_STATES
        message, params = steering_settled_sql(marker, now)
    elif state in _STEERING_OPEN_BY_FILTER:
        states = _STEERING_OPEN_BY_FILTER[state]
        message, params = steering_open_sql(marker, now)
    else:
        return "1=0", []
    slots = ",".join(marker for _ in states)
    return f"(sr.state IN ({slots}) AND {message})", [*states, *params]


def message_recipient_match_clause(
    marker: str,
    *,
    state: str | None,
    session_id: str | None,
    actor_id: int,
    now: Any,
) -> tuple[str, list[Any]]:
    """Build the shared recipient/state predicate for message list reads.

    ``now`` is the bound read instant: a session or person receipt still
    open past its message's expiry matches ``expired`` rather than its
    stored state, so the filter agrees with what the rows display.

    The steering branch does not depend on a session row: a role-addressed
    row has a recipient whether or not any session is holding it --
    ``awaiting_seat`` with no seat at all, or ``delivered`` to a seat that
    was handed it on acquire and never got a session-recipient row of its
    own. A cancelled or expired steering message is settled, never open. Narrowing to
    ``sr.seat_session_id`` only kicks in when the caller filtered to one
    exact session, matching the plain session-recipient branch above it.
    """
    session_state, session_params = _session_state_clause(marker, state, now)
    session_filter = ""
    if session_id is not None:
        session_filter = f" AND r.session_id={marker}"
        session_params.append(session_id)
    branches = [
        "EXISTS (SELECT 1 FROM session_message_recipients r WHERE "
        f"r.message_id=m.message_id AND {session_state}{session_filter})"
    ]
    params = list(session_params)
    steering_state, steering_params = _steering_state_clause(marker, state, now)
    seat_filter = ""
    seat_params: list[Any] = []
    if session_id is not None:
        seat_filter = f" AND sr.seat_session_id={marker}"
        seat_params.append(session_id)
    branches.append(
        "EXISTS (SELECT 1 FROM actor_message_recipients sr "
        f"WHERE sr.message_id=m.message_id AND sr.recipient_kind={marker} "
        f"AND {steering_state}{seat_filter})"
    )
    params.extend([STEERING_KIND, *steering_params, *seat_params])
    if session_id is None:
        queued_clause, queued_params = queued_message_clause(
            marker, state=state, now=now
        )
        branches.append(queued_clause)
        params.extend(queued_params)
        actor_state, actor_params = _actor_state_clause(marker, state, now)
        branches.append(
            "EXISTS (SELECT 1 FROM actor_message_recipients ar "
            f"WHERE ar.message_id=m.message_id AND ar.recipient_kind={marker} "
            f"AND (ar.actor_id={marker} OR m.sender_actor_id={marker}) "
            f"AND {actor_state})"
        )
        params.extend([ACTOR_KIND, actor_id, actor_id, *actor_params])
    return "(" + " OR ".join(branches) + ")", params


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
    "ENGINE_SENDER_LABEL",
    "message_details",
    "message_recipient_match_clause",
    "public_recipients",
    "sender_identity_projection",
]
