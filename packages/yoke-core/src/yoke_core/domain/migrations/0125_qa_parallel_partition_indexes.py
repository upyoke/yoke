"""Retire subject-wide QA execution indexes after boot adds session keys.

An older server cannot recreate these unique indexes while a subject has
multiple live executions. Settle or abort all but one before rolling back.
"""

MINIMUM_SERVING_VERSION = "next-release"


def apply(conn):
    """Preserve every execution while dropping its obsolete uniqueness key."""
    conn.execute("DROP INDEX IF EXISTS idx_qa_plan_executions_active")
    conn.execute("DROP INDEX IF EXISTS idx_qa_plan_executions_standalone_active")
    conn.execute("DROP INDEX IF EXISTS idx_qa_plan_executions_deployment_member_stage_active")
