"""Pending release plans returned to the driver with a scoped-QA dispatch."""

from typing import Any

from yoke_core.domain.deployment_qa_plan_groups import run_groups
from yoke_core.domain.deployment_qa_case_failure_kinds import RED_VERDICTS
from yoke_core.domain.qa_attempt_target_currency import current_target_attempts
from yoke_core.domain.qa_latest_execution import latest_verdict_executions
from yoke_core.domain.qa_obligation_settlement import settled_obligation_sql
from yoke_core.domain.qa_pending_agent_review import pending_review_requirements
from yoke_core.domain.qa_plan_case_chain import ends_chain
from yoke_core.domain.qa_plan_partition_custody import PartitionScope, held_partition_cases


class QaDispatchResult(tuple):
    """A step-runner result carrying server-selected plans to its waiting driver."""

    def __new__(cls, code: int, message: str, pending_plans: list[dict]):
        result = super().__new__(cls, (code, message))
        result.pending_plans = pending_plans
        return result


def pending_stage_plans(conn: Any, stage: dict, run_id: str) -> list[dict]:
    """Return open plans for the driver to assess partition by partition."""
    name = str(stage["name"])
    if stage.get("scope") == "item":
        subjects = [
            (g.plan_id, g.digest) for g in run_groups(conn, run_id, name) if g.open
        ]
    else:
        plan_id = (stage.get("cases") or {}).get("plan_id")
        subjects = [(int(plan_id), "")] if plan_id else []
    found = []
    for plan_id, digest in subjects:
        row = conn.execute(
            "SELECT p.slug,pr.slug FROM qa_plans p JOIN projects pr ON pr.id=p.project_id "
            "WHERE p.id=%s",
            (plan_id,),
        ).fetchone()
        if row is None or not _has_pending_partition(conn, run_id, name, plan_id, digest):
            continue
        found.append(
            {"plan": str(row[0]), "project": str(row[1]), "target_digest": digest}
        )
    return found


def _has_pending_partition(conn, run_id, stage, plan_id, digest):
    from itertools import groupby

    from yoke_core.domain.db_helpers import query_rows

    rows = query_rows(
        conn,
        "SELECT id,plan_id,baseline_position,starting_state,wake_path,execution_target_digest "
        "FROM qa_requirements WHERE deployment_run_id=%s AND deployment_stage=%s "
        "AND deployment_member_item_id IS NULL AND plan_id=%s AND retracted_at IS NULL "
        f"AND NOT {settled_obligation_sql(conn)} AND (%s='' OR execution_target_digest=%s) "
        "ORDER BY execution_target_digest,baseline_position,case_position,id",
        (run_id, stage, plan_id, digest, digest),
    )
    if not rows:
        return False
    ids = [int(row["id"]) for row in rows]
    attempts = current_target_attempts(conn, latest_verdict_executions(conn, ids))
    pending = pending_review_requirements(conn, ids)
    scope = PartitionScope(deployment_run_id=run_id, deployment_stage=stage)
    held = held_partition_cases(conn, scope)
    for target, rows_for_target in groupby(rows, lambda row: row["execution_target_digest"]):
        chain = list(rows_for_target)
        available = True
        for ordinal, row in enumerate(chain):
            requirement = int(row["id"])
            review = pending.get(requirement)
            available = available and (
                row["wake_path"] != "manual" and requirement not in held
                and attempts.get(requirement, {}).get("verdict") not in RED_VERDICTS
                and (review is None or review.execution_target_digest != target)
            )
            if ends_chain(chain, ordinal):
                if available:
                    return True
                available = True
    return False
