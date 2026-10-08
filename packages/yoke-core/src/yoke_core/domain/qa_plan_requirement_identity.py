"""Uniqueness of item-bound case, baseline and environment obligations."""


def ensure_materialization_index(conn) -> None:
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_qa_requirement_environment_materialization "
        "ON qa_requirements(item_id,plan_id,plan_case_key,COALESCE(host_baseline,''),"
        "workflow_transition_id,COALESCE(target_env,'')) "
        "WHERE item_id IS NOT NULL AND plan_id IS NOT NULL"
    )
