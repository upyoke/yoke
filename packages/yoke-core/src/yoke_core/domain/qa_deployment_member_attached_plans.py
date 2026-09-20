"""The member's own post-deploy QA plan, resolved for a deployment stage.

An item-scoped QA stage tests one member's behaviour, so the plan that
belongs to that member is the one it should run. Until now the stage could
only reach a plan two ways: pinned in the flow, or named by a ``--plan``
flag at the wake. Neither is the member's own, and the flag is chosen under
time pressure against an already-deployed candidate -- which is how members
ended up borrowing another item's criteria, or authoring a probe whose very
first execution was against production.

An item attaches its plan the ordinary way, through
``qa_plan_item_attachments`` with the ``post_deploy`` phase, while its cases
are still editable. This resolves that attachment at stage time so the wake
needs no plan choice at all.

Resolution is live rather than frozen on purpose, and sits at exactly the
authority the ``--plan`` flag already had: it selects *which* plan runs,
while the plan's content is snapshotted onto the requirement rows as it is
materialized, against the run's own pinned target. A member snapshot that
already froze plans at admission still wins -- this only answers when
nothing else selected cases.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_obligation_settlement import obligation_settled
from yoke_core.domain.qa_plan_attachment_reads import live_item_attachment_sql


#: The phase an item-scoped deployment QA stage credits. An attachment for
#: any other phase belongs to a workflow transition, not to a deployment.
DEPLOYMENT_ATTACHMENT_PHASE = "post_deploy"


def attached_member_plan_ids(
    conn: Any,
    *,
    member_item_id: int,
    environment_id: int | None = None,
) -> list[int]:
    """Active post-deploy plans this member attached, oldest first.

    A plan bound to a different environment is skipped, matching how a
    frozen member plan is selected, so an item may keep one plan per
    environment its flow deploys to.
    """
    rows = query_rows(
        conn,
        "SELECT a.plan_id,p.target_environment_id FROM qa_plan_item_attachments a "
        "JOIN qa_plans p ON p.id=a.plan_id "
        "WHERE a.item_id=%s AND a.qa_phase=%s AND p.retired_at IS NULL "
        f"AND {live_item_attachment_sql(conn, 'a')} "
        "ORDER BY a.plan_id",
        (int(member_item_id), DEPLOYMENT_ATTACHMENT_PHASE),
    )
    selected: list[int] = []
    for row in rows:
        plan_environment = row["target_environment_id"]
        if plan_environment is not None and int(plan_environment) != int(
            environment_id or 0
        ):
            continue
        selected.append(int(row["plan_id"]))
    return selected


def delivery_answered_plan_ids(
    conn: Any,
    *,
    member_item_id: int,
    plan_ids: Iterable[int],
) -> set[int]:
    """Which of these plans a deployment run already answered for this member.

    A post-deploy attachment names an obligation a deployment run collects,
    and the run admits its own copy of that plan's cases. Once every admitted
    copy has an answer, the obligation is discharged -- so a second,
    item-bound copy of the same attachment would name an obligation only a
    run that has already finished could ever answer. Callers use this to
    avoid creating that copy, not to decide any verdict.

    A plan qualifies only when a run admitted at least one of its cases for
    this member and every admitted case is answered; a partly-answered plan
    still owes what it owes.
    """
    wanted = tuple(dict.fromkeys(int(plan_id) for plan_id in plan_ids))
    if not wanted:
        return set()
    placeholders = ", ".join(["%s"] * len(wanted))
    rows = query_rows(
        conn,
        "SELECT id,plan_id,waived_at,superseded_by_requirement_id,retracted_at "
        "FROM qa_requirements "
        "WHERE deployment_member_item_id=%s AND deployment_run_id IS NOT NULL "
        f"AND plan_id IN ({placeholders})",
        (int(member_item_id), *wanted),
    )
    answered: dict[int, bool] = {}
    for row in rows:
        plan_id = int(row["plan_id"])
        settled = obligation_settled(row) or _latest_verdict(conn, row["id"]) == "pass"
        answered[plan_id] = answered.get(plan_id, True) and settled
    return {plan_id for plan_id, every_case in answered.items() if every_case}


def attachments_still_owed(
    conn: Any,
    *,
    member_item_id: int,
    attachments: Mapping[int, Any],
) -> tuple[dict[int, Any], bool]:
    """Drop the attachments a delivery already answered; report whether any.

    A fresh item-bound copy of an attachment a run has already collected
    could only be answered by a run that has already finished, so it is an
    obligation nothing can discharge -- which is exactly what stranded items
    at their own close-out after supplying the very evidence asked of them.
    """
    if not attachments:
        return dict(attachments), False
    answered = delivery_answered_plan_ids(
        conn, member_item_id=int(member_item_id), plan_ids=tuple(attachments)
    )
    if not answered:
        return dict(attachments), False
    return (
        {
            plan_id: attachment
            for plan_id, attachment in attachments.items()
            if plan_id not in answered
        },
        True,
    )


def _latest_verdict(conn: Any, requirement_id: Any) -> str:
    from yoke_core.domain.qa_requirement_supersession import latest_verdict

    return latest_verdict(conn, int(requirement_id))


def attached_member_plans(
    conn: Any,
    subject: Mapping[str, Any],
    *,
    target: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Snapshot the member's attached plans in the shape the stage expects."""
    member_item_id = subject.get("member_item_id")
    if member_item_id is None:
        # A run-scoped stage has no member, so no member plan to attach.
        return []
    environment = target.get("environment")
    environment_id = (
        environment.get("id") if isinstance(environment, Mapping) else None
    )
    plan_ids = attached_member_plan_ids(
        conn,
        member_item_id=int(member_item_id),
        environment_id=environment_id,
    )
    if not plan_ids:
        return []

    from yoke_core.domain.deployment_requirement_snapshots import _plan_snapshot

    return [
        {
            "attachment": {"qa_phase": DEPLOYMENT_ATTACHMENT_PHASE},
            **_plan_snapshot(
                conn, int(plan_id), project_id=int(subject["project_id"])
            ),
        }
        for plan_id in plan_ids
    ]


__all__ = [
    "DEPLOYMENT_ATTACHMENT_PHASE",
    "attached_member_plan_ids",
    "attachments_still_owed",
    "delivery_answered_plan_ids",
    "attached_member_plans",
]
