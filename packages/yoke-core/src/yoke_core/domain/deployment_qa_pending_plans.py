"""Pending release plans returned to the driver with a scoped-QA dispatch."""

from typing import Any

from yoke_core.domain.deployment_qa_plan_groups import run_groups


class QaDispatchResult(tuple):
    """A step-runner result carrying server-selected plans to its waiting driver."""

    def __new__(cls, code: int, message: str, pending_plans: list[dict]):
        result = super().__new__(cls, (code, message))
        result.pending_plans = pending_plans
        return result


def pending_stage_plans(conn: Any, stage: dict, run_id: str) -> list[dict]:
    """Return runnable group plans or the run stage's own selected plan.

    Manual evidence stays with its owner; a pending review is already captured.
    The target digest distinguishes later groups of the same plan.
    """
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
        rows = conn.execute(
            "SELECT wake_path FROM qa_requirements WHERE deployment_run_id=%s "
            "AND deployment_stage=%s AND plan_id=%s AND retracted_at IS NULL "
            "AND (%s='' OR execution_target_digest=%s)",
            (run_id, name, plan_id, digest, digest),
        ).fetchall()
        if not rows or any(row[0] == "manual" for row in rows):
            continue
        review = conn.execute(
            "SELECT 1 FROM qa_plan_executions WHERE deployment_run_id=%s "
            "AND deployment_stage=%s AND state='awaiting_walk_review' "
            "AND (%s='' OR execution_target_digest=%s) LIMIT 1",
            (run_id, name, digest, digest),
        ).fetchone()
        if review:
            continue
        row = conn.execute(
            "SELECT p.slug,pr.slug FROM qa_plans p JOIN projects pr ON pr.id=p.project_id "
            "WHERE p.id=%s",
            (plan_id,),
        ).fetchone()
        found.append(
            {"plan": str(row[0]), "project": str(row[1]), "target_digest": digest}
        )
    return found
