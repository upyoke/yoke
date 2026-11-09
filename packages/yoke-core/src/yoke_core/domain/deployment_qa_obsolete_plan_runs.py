"""Identify failed releases composed with obsolete post-deploy plan copies."""

from typing import Any

FAILED_OBSOLETE_PLAN_RUNS = (
    "SELECT DISTINCT d.id FROM deployment_runs d WHERE d.status='failed' "
    "AND (EXISTS (SELECT 1 FROM deployment_run_items m WHERE m.run_id=d.id "
    "AND jsonb_array_length(COALESCE(NULLIF(m.requirement_snapshot,'')::jsonb->'plans',"
    "'[]'::jsonb))>0 AND EXISTS (SELECT 1 FROM qa_requirements q WHERE "
    "q.deployment_run_id=d.id AND q.deployment_member_item_id=m.item_id "
    "AND q.plan_id IN (SELECT (p->'plan'->>'id')::bigint FROM jsonb_array_elements("
    "NULLIF(m.requirement_snapshot,'')::jsonb->'plans') p))) "
    "OR EXISTS (SELECT 1 FROM qa_requirements s WHERE "
    "s.deployment_run_id=d.id AND s.deployment_member_item_id IS NULL AND s.plan_id IS NOT NULL "
    "AND jsonb_typeof(NULLIF(s.execution_target_json,'')::jsonb->'deployment'->'shared_plan')"
    "='object' AND NOT jsonb_exists(NULLIF(s.execution_target_json,'')::jsonb->'deployment'"
    "->'shared_plan','group_id'))) ORDER BY d.id"
)


def failed_obsolete_plan_run_ids(conn: Any) -> set[str]:
    """Old plan copies cannot be retried through current plan groups."""
    return {str(row[0]) for row in conn.execute(FAILED_OBSOLETE_PLAN_RUNS).fetchall()}
