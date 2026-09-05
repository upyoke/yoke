"""Compose the signed-in actor's gate and message Inbox."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.actor_display import actor_display_name
from yoke_core.domain.actors import (
    ActorLabelAmbiguous,
    ActorLabelMissing,
    ActorNotFound,
)
from yoke_core.domain.actor_message_recipients import inbox_actor_messages
from yoke_core.domain.decision_request_authority import (
    pending_requests_for_actor,
)
from yoke_core.domain.decision_request_contract import MACHINE_APPROVAL
from yoke_core.domain.decision_request_disposition import (
    dispose_ended_decision_requests,
)
from yoke_core.domain.session_operator_wake_notice import (
    settle_operator_wake_notices,
)


def _requester_named(conn: Any, row: dict[str, Any]) -> dict[str, Any]:
    """Name who asked for the machine, so the approver reads a person.

    The originator is the actor who installed Yoke on that machine and
    authenticated there. Approving does not make the approver its owner,
    so the row says whose machine it is before anyone answers.
    """
    actor_id = row.get("originator_actor_id")
    label = None
    if actor_id is not None:
        try:
            label = actor_display_name(conn, int(actor_id))
        except (ActorNotFound, ActorLabelMissing, ActorLabelAmbiguous):
            label = None
    return {**row, "originator_actor_label": label}


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

    Machine approvals are the one gate answered somewhere else. They are
    org-scoped rather than project-scoped, and what an approver needs
    beside the decision — which machine, its one-time code, who asked for
    it — is the Machines page. They travel in their own key so that page
    reads them from this one authority rather than a second one.
    """
    dispose_ended_decision_requests(conn, project_ids=project_ids)
    settle_operator_wake_notices(conn, actor_id=actor_id)
    decisions = pending_requests_for_actor(
        conn,
        actor_id,
        project_ids=project_ids,
    )
    actor_messages = inbox_actor_messages(
        conn, actor_id=actor_id, include_read=include_read
    )
    return {
        "needs_decision": [row for row in decisions if row["kind"] != MACHINE_APPROVAL],
        "machine_approvals": [
            _requester_named(conn, row)
            for row in decisions
            if row["kind"] == MACHINE_APPROVAL
        ],
        "messages": actor_messages["messages"],
        "pending_actor_message_count": actor_messages["pending_count"],
    }


__all__ = ["inbox_for_actor"]
