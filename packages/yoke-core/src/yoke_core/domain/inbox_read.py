"""Compose the signed-in actor's gate and message Inbox."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.actor_message_recipients import inbox_actor_messages
from yoke_core.domain.actor_decision_queue import (
    pending_requests_for_actor,
    recently_decided_requests_for_actor,
)
from yoke_core.domain.decision_request_contract import RETIRED_DECISION_KINDS
from yoke_core.domain.delivery_notice_kind import classify_messages
from yoke_core.domain.decision_request_disposition import (
    dispose_ended_decision_requests,
)
from yoke_core.domain.session_operator_wake_notice import (
    settle_operator_wake_notices,
)


def inbox_for_actor(
    conn: Any,
    *,
    actor_id: int,
    project_ids: list[int] | None,
    include_read: bool,
) -> dict[str, Any]:
    """Converge dead asks, then compose what still needs a person.

    Two content types reach a person in the Inbox itself and they are the
    only two: a gate waiting on their decision, and a message someone sent
    them. Rendering the Inbox is where a decision whose subject already
    ended does its damage, so it is also where convergence earns its keep:
    the reader never sees a gate that gates nothing. A desktop wake notice
    converges the same way and for the same reason — it reports an absence,
    and the absence ends without anyone telling the notice.

    Retired decision kinds remain readable through their history but do not
    appear as current Inbox work. Machine admission uses its own engine store.
    A short tail of settled gates travels beside what still waits so the
    actor can see the answers they just gave after a reload.
    """
    dispose_ended_decision_requests(conn, project_ids=project_ids)
    settle_operator_wake_notices(conn, actor_id=actor_id)
    decisions = pending_requests_for_actor(
        conn,
        actor_id,
        project_ids=project_ids,
    )
    settled = recently_decided_requests_for_actor(
        conn,
        actor_id,
        project_ids=project_ids,
    )
    actor_messages = inbox_actor_messages(
        conn, actor_id=actor_id, include_read=include_read
    )
    # A delivery notice reports; a message from a person may ask, and the
    # Inbox draws them apart.
    messages = classify_messages(actor_messages["messages"])
    return {
        "needs_decision": [
            row
            for row in (*decisions, *settled)
            if row["kind"] not in RETIRED_DECISION_KINDS
        ],
        "messages": messages,
        "pending_actor_message_count": actor_messages["pending_count"],
    }


__all__ = ["inbox_for_actor"]
