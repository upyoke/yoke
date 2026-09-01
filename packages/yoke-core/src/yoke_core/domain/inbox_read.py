"""Compose the signed-in actor's decision, notification, and message Inbox."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.actor_message_recipients import inbox_actor_messages
from yoke_core.domain.decision_request_contract import MACHINE_APPROVAL
from yoke_core.domain.decision_requests import pending_requests_for_actor
from yoke_core.domain.inbox_notifications import notification_rows


def inbox_for_actor(
    conn: Any,
    *,
    actor_id: int,
    project_ids: list[int] | None,
    include_read: bool,
) -> dict[str, Any]:
    decisions = pending_requests_for_actor(
        conn,
        actor_id,
        project_ids=project_ids,
    )
    decisions = [row for row in decisions if row["kind"] != MACHINE_APPROVAL]
    notifications = notification_rows(
        conn,
        actor_id,
        unread_only=not include_read,
    )
    if project_ids is not None:
        allowed = set(project_ids)
        notifications = [
            row
            for row in notifications
            if row.get("project_id") is None or int(row["project_id"]) in allowed
        ]
    actor_messages = inbox_actor_messages(
        conn, actor_id=actor_id, include_read=include_read
    )
    return {
        "needs_decision": [row for row in decisions if row["blocking"]],
        "requests": [row for row in decisions if not row["blocking"]],
        "notifications": notifications,
        "messages": actor_messages["messages"],
        "pending_actor_message_count": actor_messages["pending_count"],
    }


__all__ = ["inbox_for_actor"]
