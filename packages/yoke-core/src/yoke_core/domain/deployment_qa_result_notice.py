"""Report a settled QA stage result to the audience its flow configured.

This is the third notification surface on a release, and it is
deliberately not either of the other two. The stage-wait and
human-verdict notices address SESSIONS — the agent that owes the work,
or the one parked for a decision — because each asks somebody to act.
This one addresses PEOPLE through the actor Inbox and asks for nothing:
it reports what a stage decided to whoever the flow said should hear it.
An item owner who is also in that audience legitimately receives this
notice and the separate item-done notice, because they are different
events about different things.

Audience comes from the stage's own ``notification`` policy, which the
flow definition already validates: ``roles`` naming project role
holders, ``actors`` naming members outright, and ``item_owners`` meaning
the owners of the items the result covers. The policy carries no
ANY/ALL mode by construction — nothing here is a gate — so the audience
is simply the union, and an empty one means nobody was configured to
hear it.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Optional

from yoke_contracts.session_control.models import RecipientSelector
from yoke_core.domain.deployment_item_owner import item_owner_actor
from yoke_core.domain.delivery_notice_kind import QA_RESULT_NOTICE_PREFIX
from yoke_core.domain.deployment_qa_stage_outcome import (
    OUTCOME_DISCHARGED,
    OUTCOME_PASSED,
    OUTCOME_REJECTED,
)
from yoke_core.domain.session_message_service import send_message

#: A stage result worth reporting. A stage still waiting is not one: the
#: agent wake already addressed that, and this audience cannot act on it. A
#: discharge is: the member was released without its cases passing, which is
#: precisely what its owner needs told rather than left to infer from a run
#: that simply moved on.
REPORTABLE_OUTCOMES = frozenset(
    {OUTCOME_PASSED, OUTCOME_REJECTED, OUTCOME_DISCHARGED}
)


def qa_result_idempotency_key(
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
    outcome: str,
    target_digest: str = "",
) -> str:
    """One notice per stage subject, outcome, and pinned-target attempt."""
    subject = "run" if member_item_id is None else str(member_item_id)
    return (
        f"{QA_RESULT_NOTICE_PREFIX}{run_id}:{stage_name}:{subject}:"
        f"{outcome}:{target_digest}"
    )


def qa_result_message(
    *,
    run_id: str,
    stage_name: str,
    subject: str,
    outcome: str,
    target_tier: str,
    revision: str,
) -> str:
    """Report the decision, what it covered, and where the evidence lives."""
    rev = (revision or "")[:12] or "an unresolved revision"
    target = target_tier or "an unspecified target"
    verdict = {
        OUTCOME_PASSED: "passed",
        OUTCOME_DISCHARGED: (
            "was discharged without its cases passing, by waiver or by a "
            "corrected case superseding them"
        ),
    }.get(outcome, "was rejected")
    return (
        f"Deployment run {run_id} QA stage {stage_name!r} {verdict} for "
        f"{subject} on {target} at {rev}. This is informational — nothing to "
        "approve and nothing to acknowledge. Its evidence is on the run: "
        f"'yoke deployment-runs get {run_id}'."
    )


def _role_holders(conn: Any, *, project_id: int, roles: tuple[str, ...]) -> set[int]:
    if not roles:
        return set()
    placeholders = ",".join("%s" for _ in roles)
    rows = conn.execute(
        "SELECT DISTINCT apr.actor_id FROM actor_project_roles apr "
        "JOIN actors a ON a.id = apr.actor_id AND a.kind = 'human' "
        "JOIN roles r ON r.id = apr.role_id "
        f"WHERE apr.project_id = %s AND r.name IN ({placeholders})",
        (int(project_id), *roles),
    ).fetchall()
    return {int(row["actor_id"] if hasattr(row, "keys") else row[0]) for row in rows}


def notification_audience(
    conn: Any,
    *,
    notification: Mapping[str, Any] | None,
    project_id: int,
    member_item_ids: tuple[int, ...],
) -> list[int]:
    """The human members this stage's policy says should hear its result.

    ``[]`` means the stage configured no notification, or configured one
    whose audience resolves to nobody — which is a real answer the caller
    reports rather than a failure.
    """
    if not isinstance(notification, Mapping) or not notification.get("enabled"):
        return []
    recipients = notification.get("recipients")
    if not isinstance(recipients, Mapping):
        return []
    audience: set[int] = set()
    roles = tuple(
        str(value) for value in (recipients.get("roles") or []) if str(value).strip()
    )
    audience |= _role_holders(conn, project_id=project_id, roles=roles)
    for value in recipients.get("actors") or []:
        try:
            audience.add(int(value))
        except (TypeError, ValueError):
            continue
    if recipients.get("item_owners"):
        for item_id in member_item_ids:
            owner = item_owner_actor(conn, item_id)
            if owner is not None:
                audience.add(owner)
    return sorted(audience)


def notify_qa_stage_result(
    conn: Any,
    *,
    notification: Mapping[str, Any] | None,
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
    project_id: int,
    outcome: str,
    subject: str,
    target_tier: str = "",
    revision: str = "",
    target_digest: str = "",
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Report one settled stage result to its configured audience.

    ``notified`` lists the members reached; an empty list with a
    ``reason`` covers a stage that configured no audience, an audience
    that resolved to nobody, and an outcome this surface does not report.
    """
    if outcome not in REPORTABLE_OUTCOMES:
        return {
            "notified": [],
            "reason": f"outcome {outcome!r} is not a settled stage result",
        }
    audience = notification_audience(
        conn,
        notification=notification,
        project_id=project_id,
        member_item_ids=(member_item_id,) if member_item_id is not None else (),
    )
    if not audience:
        return {
            "notified": [],
            "reason": "this stage configured no notification audience",
        }
    created = send_message(
        conn,
        # The sender shares an organization with every configured member,
        # which is what addressing a human requires; the lowest audience
        # id is a deterministic choice among them rather than a new
        # authority concept.
        actor_id=audience[0],
        sender_session_id=None,
        selector=RecipientSelector(actors=[str(value) for value in audience]),
        body=qa_result_message(
            run_id=run_id,
            stage_name=stage_name,
            subject=subject,
            outcome=outcome,
            target_tier=target_tier,
            revision=revision,
        ),
        idempotency_key=qa_result_idempotency_key(
            run_id, stage_name, member_item_id, outcome, target_digest
        ),
        idempotency_intent_only=True,
        now=now or datetime.now(timezone.utc),
        commit=False,
    )
    return {
        "notified": audience,
        "message_id": str(created["message_id"]),
        "reason": "",
    }


__all__ = [
    "OUTCOME_DISCHARGED",
    "OUTCOME_PASSED",
    "OUTCOME_REJECTED",
    "REPORTABLE_OUTCOMES",
    "notification_audience",
    "notify_qa_stage_result",
    "qa_result_idempotency_key",
    "qa_result_message",
]
