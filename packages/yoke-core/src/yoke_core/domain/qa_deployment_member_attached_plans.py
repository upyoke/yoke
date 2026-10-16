"""Resolve member post-deploy attachments and credit their delivered plan groups.

Attachments select a member's obligations. Stage materialization groups each
attached plan by source revision and observed target, and the shared case
verdict answers every attaching member. A private source requirement does not
need a duplicate item-bound execution after its delivery group passed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_obligation_settlement import (
    obligation_settled,
    requirement_retracted_at_select,
)
from yoke_core.domain.qa_plan_attachment_reads import live_item_attachment_sql


def stage_environment_id_for_plan_selection(
    conn: Any, target: Mapping[str, Any]
) -> int | None:
    """Persistent environment this stage is asking against.

    A ``run_preview`` target has no environment id of its own. It stands in
    for the run's persistent ``target_environment_id``, which is how a plan
    bound to prod stays selectable at preview and still skips a plan bound
    to a different environment.
    """
    environment = target.get("environment")
    if not isinstance(environment, Mapping):
        return None
    raw_id = environment.get("id")
    if raw_id is not None:
        return int(raw_id)
    if str(environment.get("kind") or "") != "run_preview":
        return None
    deployment = target.get("deployment")
    run_id = (
        str(deployment.get("run_id") or "") if isinstance(deployment, Mapping) else ""
    )
    if not run_id:
        return None
    row = conn.execute(
        "SELECT target_environment_id FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    value = row["target_environment_id"] if hasattr(row, "keys") else row[0]
    return int(value) if value is not None else None


def plan_matches_stage_environment(
    plan_environment_id: Any, stage_environment_id: int | None
) -> bool:
    """True when an unbound plan, or a plan bound to this stage's environment."""
    if plan_environment_id is None:
        return True
    return int(plan_environment_id) == int(stage_environment_id or 0)


#: The phase an item-scoped deployment QA stage credits. An attachment for
#: any other phase belongs to a workflow transition, not to a deployment.
DEPLOYMENT_ATTACHMENT_PHASE = "post_deploy"


def attached_member_plan_ids(conn, *, member_item_id, environment_id=None):
    from yoke_core.domain.deployment_qa_presentation_reads import presentation_read

    return presentation_read(
        conn,
        ("qa_live_attached_plans", int(member_item_id), environment_id),
        lambda: _read_attached_member_plan_ids(
            conn,
            member_item_id=member_item_id,
            environment_id=environment_id,
        ),
    )


def _read_attached_member_plan_ids(
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
    from yoke_core.domain.deployment_qa_presentation_facts import attachment_rows
    from yoke_core.domain.deployment_qa_presentation_reads import presentation_read

    rows = attachment_rows(conn, int(member_item_id))
    if rows is not None:
        rows = [
            row
            for row in rows
            if row["live"]
            and row["live_plan_id"] is not None
            and row["retired_at"] is None
        ]
    else:
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
        if not plan_matches_stage_environment(
            row["target_environment_id"], environment_id
        ):
            from yoke_core.domain.qa_plan_case_definition import plan_cases
            from yoke_core.domain.qa_plan_case_targets import case_target_envs

            environment = presentation_read(
                conn,
                ("qa_attachment_environment", environment_id),
                lambda: conn.execute(
                    "SELECT name FROM environments WHERE id=%s", (environment_id,)
                ).fetchone(),
            )
            name = str(environment[0]) if environment else ""
            plan_id = int(row["plan_id"])

            def read_cases():
                from yoke_core.domain.deployment_qa_shared_plan_reads import (
                    presented_plan_rows,
                )
                from yoke_core.domain.qa_plan_case_definition import (
                    materialized_plan_cases,
                )

                batch = presented_plan_rows(conn, plan_id)
                if batch is None:
                    return plan_cases(conn, plan_id)
                return materialized_plan_cases(
                    [
                        {"plan_slug": batch[0]["slug"], **dict(case)}
                        for case in batch[1]
                    ],
                    plan_id,
                )

            cases = presentation_read(
                conn,
                ("qa_attachment_cases", plan_id),
                read_cases,
            )
            if not any(name in case_target_envs(case) for case in cases):
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
        f"SELECT id,plan_id,plan_case_key,host_baseline,target_env,waived_at,superseded_by_requirement_id,{requirement_retracted_at_select(conn)},deployment_run_id,deployment_stage,deployment_member_item_id,execution_target_digest,execution_target_json "
        "FROM qa_requirements "
        "WHERE (deployment_member_item_id=%s OR (deployment_member_item_id IS NULL "
        "AND EXISTS (SELECT 1 FROM deployment_run_items m WHERE m.run_id=deployment_run_id AND m.item_id=%s))) "
        "AND deployment_run_id IS NOT NULL "
        f"AND plan_id IN ({placeholders})",
        (int(member_item_id), int(member_item_id), *wanted),
    )
    answered: dict[int, bool] = {}
    targeted: dict[tuple, bool] = {}
    shared_digests = {}
    for row in rows:
        if row["deployment_member_item_id"] is None:
            from yoke_core.domain.deployment_qa_shared_plans import (
                member_group_digests,
                shared_target_identity,
            )

            if not shared_target_identity(row["execution_target_json"]):
                continue
            key = (row["deployment_run_id"], row["deployment_stage"])
            if key not in shared_digests:
                shared_digests[key] = member_group_digests(conn, *key, member_item_id)
            if row["execution_target_digest"] not in shared_digests[key]:
                continue
        plan_id = int(row["plan_id"])
        settled = obligation_settled(row) or _latest_verdict(conn, row["id"]) == "pass"
        answered[plan_id] = answered.get(plan_id, True) and settled
        key = (plan_id, row["plan_case_key"], row["host_baseline"], row["target_env"])
        targeted[key] = targeted.get(key, True) and settled
    from yoke_core.domain.qa_plan_case_definition import case_baselines, plan_cases
    from yoke_core.domain.qa_plan_case_targets import case_target_envs

    for plan_id in wanted:
        for case in plan_cases(conn, plan_id):
            for name in case_target_envs(case):
                for baseline in case_baselines(case):
                    if not targeted.get(
                        (plan_id, case["case_key"], baseline, name), False
                    ):
                        answered[plan_id] = False
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
    lock_plans: bool = True,
) -> list[dict[str, Any]]:
    """Snapshot the member's attached plans in the shape the stage expects."""
    member_item_id = subject.get("member_item_id")
    if member_item_id is None:
        # A run-scoped stage has no member, so no member plan to attach.
        return []
    plan_ids = attached_member_plan_ids(
        conn,
        member_item_id=int(member_item_id),
        environment_id=stage_environment_id_for_plan_selection(conn, target),
    )
    if not plan_ids:
        return []

    from yoke_core.domain.deployment_requirement_snapshots import _plan_snapshot

    from yoke_core.domain.deployment_qa_presentation_reads import presentation_read

    project_id = int(subject.get("member_project_id") or subject["project_id"])

    def snapshot(plan_id):
        def read():
            return _plan_snapshot(
                conn, plan_id, project_id=project_id, lock_plan=lock_plans
            )

        return (
            read()
            if lock_plans
            else presentation_read(
                conn,
                ("qa_attached_plan_snapshot", plan_id, project_id),
                read,
            )
        )

    return [
        {
            "attachment": {"qa_phase": DEPLOYMENT_ATTACHMENT_PHASE},
            **snapshot(int(plan_id)),
        }
        for plan_id in plan_ids
    ]


__all__ = [
    "DEPLOYMENT_ATTACHMENT_PHASE",
    "attached_member_plan_ids",
    "attachments_still_owed",
    "delivery_answered_plan_ids",
    "attached_member_plans",
    "plan_matches_stage_environment",
    "stage_environment_id_for_plan_selection",
]
