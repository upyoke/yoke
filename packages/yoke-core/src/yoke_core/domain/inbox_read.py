"""Compose the signed-in actor's gate and message Inbox."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.actor_message_recipients import inbox_actor_messages
from yoke_core.domain.decision_request_contract import MACHINE_APPROVAL
from yoke_core.domain.decision_request_disposition import (
    dispose_ended_decision_requests,
)
from yoke_core.domain.decision_requests import pending_requests_for_actor


def inbox_for_actor(
    conn: Any,
    *,
    actor_id: int,
    project_ids: list[int] | None,
    include_read: bool,
) -> dict[str, Any]:
    """Converge dead asks, then compose what still needs a person.

    Two content types reach a person here and they are the only two: a gate
    waiting on their decision, and a message someone sent them. Rendering
    the Inbox is where a decision whose subject already ended does its
    damage, so it is also where convergence earns its keep: the reader never
    sees a gate that gates nothing.
    """
    dispose_ended_decision_requests(conn, project_ids=project_ids)
    decisions = pending_requests_for_actor(
        conn,
        actor_id,
        project_ids=project_ids,
    )
    actor_messages = inbox_actor_messages(
        conn, actor_id=actor_id, include_read=include_read
    )
    return {
        "needs_decision": [
            row for row in decisions if row["kind"] != MACHINE_APPROVAL
        ],
        "messages": actor_messages["messages"],
        "pending_actor_message_count": actor_messages["pending_count"],
    }


__all__ = ["inbox_for_actor"]
