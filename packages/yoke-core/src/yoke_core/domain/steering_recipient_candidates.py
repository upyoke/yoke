"""Unsettled role-addressed rows, loaded without walking settled history.

A project's steering recipient table keeps every report it ever received.
Most of those rows are finished: cancelled messages, acknowledged seats,
and mail still sitting with a live seat. Membership and reply checks are
only meaningful for the rest, so this read drops the finished set in SQL
before any of that work runs. Bodies stay off this query; the drain path
attaches them to the few rows it will actually hand over.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.actor_message_recipient_schema import (
    TABLE as RECIPIENT_TABLE,
)


STEERING_KIND = "steering"
STATE_ACKNOWLEDGED = "acknowledged"
STATE_DELIVERED = "delivered"

_CANDIDATE_COLUMNS = (
    "r.message_id AS message_id, r.state AS state, "
    "r.steering_scope AS steering_scope, r.sender_item_id AS sender_item_id, "
    "r.project_id AS project_id, r.seat_session_id AS seat_session_id, "
    "r.created_at AS created_at, m.sender_session_id AS sender_session_id, "
    "m.created_at AS sent_at, seat.ended_at AS seat_ended_at, "
    "seat.terminated_at AS seat_terminated_at"
)


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def load_unsettled_steering_rows(conn: Any, project_id: int) -> list[dict[str, Any]]:
    """Project steering recipients that are not yet settled or live-held."""
    marker = _marker(conn)
    rows = conn.execute(
        f"SELECT {_CANDIDATE_COLUMNS} "
        f"FROM {RECIPIENT_TABLE} r "
        "JOIN session_messages m ON m.message_id = r.message_id "
        "LEFT JOIN harness_sessions seat ON seat.session_id = r.seat_session_id "
        f"WHERE r.recipient_kind = {marker} AND r.project_id = {marker} "
        f"AND m.cancelled_at IS NULL AND r.state <> {marker} "
        f"AND NOT (r.state = {marker} AND r.seat_session_id IS NOT NULL "
        "AND seat.ended_at IS NULL AND seat.terminated_at IS NULL) "
        "ORDER BY m.created_at DESC, r.message_id DESC",
        (STEERING_KIND, int(project_id), STATE_ACKNOWLEDGED, STATE_DELIVERED),
    ).fetchall()
    return [dict(row) for row in rows]


def attach_message_bodies(
    conn: Any, rows: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Add each remaining row's body in one read, preserving input order."""
    attached = [dict(row) for row in rows]
    if not attached:
        return attached
    ids = tuple(str(row["message_id"]) for row in attached)
    marker = _marker(conn)
    found = conn.execute(
        "SELECT message_id, body FROM session_messages "
        f"WHERE message_id IN ({','.join(marker for _ in ids)})",
        ids,
    ).fetchall()
    bodies = {str(dict(row)["message_id"]): dict(row)["body"] for row in found}
    for row in attached:
        row["body"] = bodies.get(str(row["message_id"]), "")
    return attached


__all__ = ["attach_message_bodies", "load_unsettled_steering_rows"]
