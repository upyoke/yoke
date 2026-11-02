"""Pinned or current cases used to display shared plans awaiting their group."""

from typing import Any
from yoke_core.domain.db_helpers import query_rows


def pending_plans(
    conn: Any, plan_ids: set[int], groups: dict, runs: list[str]
) -> dict[int, dict]:
    """Owed plans with no plan group yet, with their cases, in one read."""
    if not plan_ids:
        return {}
    plans: dict[int, dict] = {}
    for group in groups.values():
        if group["plan_id"] in plan_ids and group["run_id"] in runs:
            plans[group["plan_id"]] = {
                key: group[key] for key in ("plan_id", "plan", "plan_name", "cases")
            }
    unpinned = plan_ids - plans.keys()
    if not unpinned:
        return plans
    for row in query_rows(
        conn,
        "SELECT p.id AS plan_id,p.slug,p.name,p.project_id,c.case_key,"
        "c.method_id,m.name AS method_name,c.instructions "
        "FROM qa_plans p JOIN qa_plan_cases c ON c.plan_id=p.id "
        "LEFT JOIN qa_methods m ON m.id=c.method_id "
        "WHERE p.id=ANY(%s) ORDER BY p.id,c.position",
        (sorted(unpinned),),
    ):
        plan = plans.setdefault(
            int(row["plan_id"]),
            {
                "plan_id": int(row["plan_id"]),
                "plan": row["slug"],
                "plan_name": row["name"] or row["slug"],
                "cases": [],
            },
        )
        plan["cases"].append(
            {
                "plan_id": plan["plan_id"],
                "plan": plan["plan"],
                "project_id": row["project_id"],
                "case_key": row["case_key"],
                "method_id": row["method_id"],
                "method_name": row["method_name"],
                "instructions": row["instructions"],
                "qa_phase": "post_deploy",
                "pending_obligation": True,
            }
        )
    return plans
