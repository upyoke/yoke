"""Which post-deploy plans a member attaches for a deployment stage's environment.

Plan groups (:mod:`deployment_qa_plan_groups`) read these to know which plans
a release owes and which members a group answers.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_rows
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


__all__ = [
    "DEPLOYMENT_ATTACHMENT_PHASE",
    "attached_member_plan_ids",
    "plan_matches_stage_environment",
    "stage_environment_id_for_plan_selection",
]
