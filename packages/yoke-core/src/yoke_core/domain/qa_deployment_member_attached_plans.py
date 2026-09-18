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

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_rows


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
    "attached_member_plans",
]
