"""Addressed-event fan-out and per-actor notification read state."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.decision_request_contract import (
    DECISION_RESOLVED,
    DEPLOYMENT_RUN_COMPLETED,
    IN_APP_NOTIFICATION_KINDS,
    ITEM_BLOCK_STATE_CHANGED,
    ITEM_BLOCKED_EVENT,
    ITEM_UNBLOCKED_EVENT,
    REQUEST_RESOLVED_EVENT,
)

_PRODUCER_NAMES = {
    DECISION_RESOLVED: (REQUEST_RESOLVED_EVENT,),
    DEPLOYMENT_RUN_COMPLETED: ("DeploymentRunSucceeded", "DeploymentRunFailed"),
    ITEM_BLOCK_STATE_CHANGED: (ITEM_BLOCKED_EVENT, ITEM_UNBLOCKED_EVENT),
}


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row_dict(row: Any) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def fan_out_in_app_notification(
    conn: Any,
    *,
    event_id: str,
    notification_kind: str,
    recipient_actor_ids: Iterable[int],
    reason: str,
    created_at: str,
) -> int:
    """Materialize one idempotent in-app delivery per addressed actor."""
    if notification_kind not in IN_APP_NOTIFICATION_KINDS:
        raise ValueError(f"unknown in-app notification kind {notification_kind!r}")
    p = _p(conn)
    event = conn.execute(
        f"SELECT event_name FROM events WHERE event_id = {p}", (event_id,),
    ).fetchone()
    if event is None:
        raise LookupError(f"registered producer event {event_id!r} does not exist")
    event_name = str(event[0])
    if event_name not in _PRODUCER_NAMES[notification_kind]:
        raise ValueError(
            f"{event_name!r} cannot produce {notification_kind!r} notifications"
        )
    inserted = 0
    for actor_id in sorted({int(value) for value in recipient_actor_ids}):
        cursor = conn.execute(
            "INSERT INTO addressed_event_deliveries "
            "(channel, event_id, actor_id, notification_kind, reason, created_at) "
            f"VALUES ('in_app', {p}, {p}, {p}, {p}, {p}) "
            "ON CONFLICT(channel, event_id, actor_id) DO NOTHING",
            (event_id, actor_id, notification_kind, reason, created_at),
        )
        inserted += max(int(cursor.rowcount or 0), 0)
    return inserted


def fan_out_registered_event(
    conn: Any,
    *,
    event_id: str,
    notification_kind: str,
    event_context: Mapping[str, Any],
    reason: str,
    created_at: str,
) -> int:
    """Resolve the exact v1 recipients at the single fan-out chokepoint."""
    recipients: list[int] = []
    if notification_kind == DECISION_RESOLVED:
        request_id = event_context.get("request_id")
        if request_id is None:
            raise ValueError("decision resolution event needs request_id")
        p = _p(conn)
        row = conn.execute(
            "SELECT originator_actor_id FROM decision_requests "
            f"WHERE id = {p}",
            (int(request_id),),
        ).fetchone()
        if row is None:
            raise LookupError(f"decision request {request_id} does not exist")
        if row[0] is not None:
            recipients.append(int(row[0]))
    elif notification_kind == DEPLOYMENT_RUN_COMPLETED:
        initiator = event_context.get("initiator_actor_id")
        approvers = event_context.get("stage_approver_actor_ids") or []
        if initiator is not None:
            recipients.append(int(initiator))
        recipients.extend(int(value) for value in approvers)
    elif notification_kind == ITEM_BLOCK_STATE_CHANGED:
        owner = event_context.get("owner_actor_id")
        if owner is not None:
            recipients.append(int(owner))
    else:
        raise ValueError(f"unknown in-app notification kind {notification_kind!r}")
    return fan_out_in_app_notification(
        conn, event_id=event_id, notification_kind=notification_kind,
        recipient_actor_ids=recipients, reason=reason, created_at=created_at,
    )


def notification_rows(
    conn: Any,
    actor_id: int,
    *,
    unread_only: bool = True,
) -> list[dict[str, Any]]:
    """Return addressed projections joined to their source event."""
    p = _p(conn)
    unread = "AND d.read_at IS NULL " if unread_only else ""
    rows = conn.execute(
        "SELECT d.id, d.event_id, d.notification_kind, d.reason, "
        "d.read_at, d.created_at, e.event_name, e.project_id, "
        "e.event_outcome, e.envelope "
        "FROM addressed_event_deliveries d "
        "JOIN events e ON e.event_id = d.event_id "
        f"WHERE d.actor_id = {p} AND d.channel = 'in_app' {unread}"
        "ORDER BY d.created_at DESC, d.id DESC",
        (actor_id,),
    ).fetchall()
    result = []
    for row in rows:
        value = _row_dict(row)
        envelope = value.pop("envelope", None)
        try:
            value["event"] = json.loads(envelope) if envelope else {}
        except (TypeError, json.JSONDecodeError):
            value["event"] = {}
        result.append(value)
    return result


def mark_notification_read(
    conn: Any,
    actor_id: int,
    notification_id: int,
    read_at: str,
) -> bool:
    p = _p(conn)
    cursor = conn.execute(
        f"UPDATE addressed_event_deliveries SET read_at = {p} "
        f"WHERE id = {p} AND actor_id = {p} AND read_at IS NULL",
        (read_at, notification_id, actor_id),
    )
    return int(cursor.rowcount or 0) > 0


def mark_all_notifications_read(
    conn: Any,
    actor_id: int,
    read_at: str,
) -> int:
    p = _p(conn)
    cursor = conn.execute(
        f"UPDATE addressed_event_deliveries SET read_at = {p} "
        f"WHERE actor_id = {p} AND channel = 'in_app' AND read_at IS NULL",
        (read_at, actor_id),
    )
    return max(int(cursor.rowcount or 0), 0)


__all__ = [
    "fan_out_in_app_notification",
    "fan_out_registered_event",
    "mark_all_notifications_read",
    "mark_notification_read",
    "notification_rows",
]
