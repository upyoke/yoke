"""Whether an item's post-deploy plans were answered by closed plan groups.

Item X is credited for plan P when the run chosen to answer X's target
(:func:`latest_qa_member_run`, which admits supplemental staging runs that
contain the current landing), or a run that run superseded, holds a closed
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


def _plan_target_envs(conn: Any, plan_id: int, item_id: int) -> list[str]:
    """A formed group's frozen plan owns every environment it still owes."""
    rows = query_rows(conn,
        "SELECT DISTINCT q.execution_target_json,r.requirement_snapshot FROM qa_requirements q "
        "JOIN deployment_runs r ON r.id=(NULLIF(q.execution_target_json,'')::jsonb #>> '{deployment,run_id}') "
        "WHERE q.plan_id=%s AND q.deployment_run_id IS NOT NULL "
        "AND q.deployment_member_item_id IS NULL "
        "AND COALESCE(NULLIF(q.execution_target_json,''),'{}')::jsonb "
        "#>> '{deployment,shared_plan,group_id}' IS NOT NULL AND ("
        "q.deployment_run_id IN (SELECT run_id FROM deployment_run_items WHERE item_id=%s) "
        "OR COALESCE(q.covered_item_ids,'[]')::jsonb @> %s::jsonb)",
        (plan_id, item_id, json.dumps([item_id])))
    envs = set()
    if rows:
        for row in rows:
            target = json.loads(row["execution_target_json"])
            snapshot = json.loads(row["requirement_snapshot"] or "{}")
            pinned = (snapshot.get("plan_groups") or {}).get(str(plan_id), {})
            for case in pinned.get("cases") or [{}]:
                raw = case.get("target_envs") or []
                values = json.loads(raw) if isinstance(raw, str) else raw
                envs.update(values or [target["environment"].get("name") or ""])
        return sorted(envs)
    row = conn.execute(
        "SELECT e.name FROM qa_plans p LEFT JOIN environments e "
        "ON e.id=p.target_environment_id WHERE p.id=%s", (plan_id,)
    ).fetchone()
    default = str(row[0] or "") if row else ""
    for case in query_rows(conn, "SELECT target_envs FROM qa_plan_cases WHERE plan_id=%s", (plan_id,)):
        raw = case["target_envs"]
        values = json.loads(raw) if isinstance(raw, str) and raw else raw or []
        envs.update(values or [default])
    return sorted(envs) or [default]


def _miss(item_id: int, plan_id: int, slug: str, run: dict | None, stage: str, target_env: str, *, conn: Any) -> dict:
    from yoke_core.domain.deployment_qa_plan_groups import run_groups

    run_id = str(run["id"]) if run else ""
    groups = run_groups(conn, run_id, stage, plan_id=plan_id) if run_id else []
    command = (
        f"yoke qa plan run --deployment-run-id {run_id} --stage {stage} --plan {slug}"
        if run_id
        else (f"the next {target_env or 'target'} deployment run whose commit contains "
              f"this item's landing enrolls it and runs plan {slug} as a plan group")
    )
    if not run:
        from yoke_core.domain.deployment_item_completion_runs import (
            completion_runs, supplemental_run_carries_landing,
        )
        from yoke_core.domain.deployment_run_candidate_containment import UNDETERMINED
        from yoke_core.domain.deployment_run_member_targeting import (
            run_environment_name, supplemental_qa_run,
        )

        for candidate in completion_runs(conn, item_id, include_qa=True):
            if (candidate["status"] in {"failed", "cancelled"}
                or run_environment_name(conn, candidate["id"]) != target_env
                or not supplemental_qa_run(conn, run_id=candidate["id"], item_id=item_id)):
                continue
            verdict = supplemental_run_carries_landing(conn, candidate, item_id)
            if verdict is not None and verdict.state == UNDETERMINED:
                command = f"{verdict.reason}: {verdict.recovery}"
            break
    return {
        "id": None,
        "qa_kind": PLAN_GROUP_QA_KIND,
        "qa_phase": "post_deploy",
        "deployment_run_id": run_id or None,
        "deployment_stage": stage,
        "group_ids": [group.group_id for group in groups if group.open],
        "item_id": int(item_id),
        "plan_id": int(plan_id),
        "plan_slug": slug,
        "plan_case_key": None,
        "target_env": target_env or None,
        "recovery": command,
    }


def plan_credit_wait_reason(miss: dict) -> str:
    """Name the target-qualified credit still owed, without implying failure."""
    target = miss.get("target_env") or "target"
    groups = ", ".join(miss.get("group_ids") or [])
    subject = f"group {groups}" if groups else f"plan {miss['plan_slug']} group credit"
    run = miss.get("deployment_run_id")
    location = f" on deployment run {run}" if run else " on a containing deployment run"
    return f"Awaiting {target} {subject}{location}."


def other_target_plan_wait(conn: Any, *, item_id: int, run_id: str) -> str:
    """Expected waiting only when every remaining done obligation is another target's plan."""
    from yoke_core.domain.deployment_run_member_targeting import run_environment_name
    from yoke_core.domain.qa_item_obligation_queries import unsatisfied_blocking

    rows = unsatisfied_blocking(conn, item_id=item_id, target_status="done").rows
    environment = run_environment_name(conn, run_id)
    if not rows or not environment or any(
        row.get("qa_kind") != PLAN_GROUP_QA_KIND or not row.get("target_env")
        or row["target_env"] == environment for row in rows
    ):
        return ""
    return " ".join(plan_credit_wait_reason(row) for row in rows)


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
        for target_env in _plan_target_envs(conn, plan_id, item_id):
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
                misses.append(_miss(item_id, plan_id, slug, run, stage, target_env, conn=conn))
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


__all__ = ["PLAN_GROUP_QA_KIND", "plan_credit_misses", "plan_credit_wait_reason", "other_target_plan_wait"]
