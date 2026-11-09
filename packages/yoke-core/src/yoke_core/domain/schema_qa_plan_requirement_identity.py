"""Indexes over plan-bound QA requirements: case uniqueness and plan reads."""


def ensure_plan_requirement_indexes(conn) -> None:
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_qa_requirement_environment_materialization "
        "ON qa_requirements(item_id,plan_id,plan_case_key,COALESCE(host_baseline,''),"
        "workflow_transition_id,COALESCE(target_env,'')) "
        "WHERE item_id IS NOT NULL AND plan_id IS NOT NULL"
    )
    # Plan pages read each listed plan's requirements without scanning history.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_qa_requirements_plan ON qa_requirements(plan_id)"
    )
