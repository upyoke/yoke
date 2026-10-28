"""Whether an item's post-deploy plans were answered by closed plan groups.

Item X is credited for plan P when the run chosen to answer X's target
(:func:`latest_qa_member_run`, which admits supplemental staging runs that
recorded the delivered source), or a run that run superseded, holds a closed
group of P whose ``covered_item_ids`` contains X. A pass never reaches an item
or attachment that arrived after it: such an item is absent from the list
and is owed a new group. A verification pass never counts; groups exist only
at item-scoped deployment stages.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain.db_helpers import query_rows

PLAN_GROUP_QA_KIND = "plan_group"


def _owed_plans(conn: Any, item_id: int) -> dict[int, str]:
    """The item's live post-deploy plans, attached or project default, by slug."""
    from yoke_core.domain.deployment_qa_member_plans import default_plan_ids
    from yoke_core.domain.qa_plan_attachment_reads import live_item_attachment_sql

    ids = {
        int(row["plan_id"])
        for row in query_rows(
            conn,
            "SELECT a.plan_id FROM qa_plan_item_attachments a JOIN qa_plans p "
            "ON p.id=a.plan_id WHERE a.item_id=%s AND a.qa_phase='post_deploy' "
            f"AND p.retired_at IS NULL AND {live_item_attachment_sql(conn, 'a')}",
            (int(item_id),),
        )
    }
    ids.update(default_plan_ids(conn, item_id))
    if not ids:
        return {}
    rows = query_rows(
        conn, "SELECT id,slug FROM qa_plans WHERE id=ANY(%s)", (sorted(ids),)
    )
    return {int(row["id"]): str(row["slug"]) for row in rows}


def _plan_target_envs(conn: Any, plan_id: int) -> list[str]:
    envs: set[str] = set()
    for row in query_rows(
        conn, "SELECT target_envs FROM qa_plan_cases WHERE plan_id=%s", (int(plan_id),)
    ):
        raw = row["target_envs"]
        values = json.loads(raw) if isinstance(raw, str) and raw else raw or []
        envs.update(str(value) for value in values)
    return sorted(envs) or [""]


def _miss(item_id: int, plan_id: int, slug: str, run: dict | None, stage: str) -> dict:
    run_id = str(run["id"]) if run else ""
    command = (
        f"yoke qa plan run --deployment-run-id {run_id} --stage {stage} --plan {slug}"
        if run_id
        else "deploy the item; its release runs the plan as a plan group"
    )
    return {
        "id": None,
        "qa_kind": PLAN_GROUP_QA_KIND,
        "qa_phase": "post_deploy",
        "deployment_run_id": run_id or None,
        "item_id": int(item_id),
        "plan_id": int(plan_id),
        "plan_slug": slug,
        "plan_case_key": None,
        "target_env": None,
        "recovery": command,
    }


def plan_credit_misses(conn: Any, item_id: int) -> list[dict]:
    """One unsatisfied row per owed plan no closed group credits to this item."""
    from yoke_core.domain.deployment_item_completion_runs import latest_qa_member_run
    from yoke_core.domain.deployment_qa_member_plans import member_plan_ids
    from yoke_core.domain.deployment_qa_plan_groups import (
        lineage_run_ids,
        run_groups,
    )
    from yoke_core.domain.deployment_qa_takeover_notice import item_qa_stage_name

    misses = []
    for plan_id, slug in sorted(_owed_plans(conn, item_id).items()):
        for target_env in _plan_target_envs(conn, plan_id):
            run = latest_qa_member_run(conn, item_id=int(item_id), target_env=target_env)
            if run is not None and plan_id not in member_plan_ids(
                conn, int(item_id), str(run["id"])
            ):
                continue  # bound to another environment: this run owes it none
            credited = run is not None and any(
                group.closed and int(item_id) in (group.covered_item_ids or ())
                for group in run_groups(
                    conn, lineage_run_ids(conn, str(run["id"])), plan_id=plan_id
                )
            )
            if not credited:
                stage = item_qa_stage_name(_stages(conn, run)) if run else "item-qa"
                misses.append(_miss(item_id, plan_id, slug, run, stage))
                break
    return misses


def _stages(conn: Any, run: dict) -> list[dict]:
    rows = query_rows(
        conn,
        "SELECT f.stages FROM deployment_runs r JOIN deployment_flows f ON f.id=r.flow "
        "WHERE r.id=%s",
        (str(run["id"]),),
    )
    raw = rows[0]["stages"] if rows else "[]"
    stages = json.loads(raw) if isinstance(raw, str) else raw
    return [stage for stage in stages or [] if isinstance(stage, dict)]


__all__ = ["PLAN_GROUP_QA_KIND", "plan_credit_misses"]
