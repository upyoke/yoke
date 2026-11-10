"""Index the selective reads on the session hook and launch paths."""

from yoke_core.domain.db_backend import connection_is_postgres


def apply(conn):
    """Build transactionally; replay preserves rows and existing indexes."""
    launch = (
        "NULLIF(selector_snapshot, '')::jsonb #>> '{launch_id}'"
        if connection_is_postgres(conn)
        else "json_extract(selector_snapshot, '$.launch_id')"
    )
    completed_order = (
        "completed_at DESC NULLS LAST"
        if connection_is_postgres(conn)
        else "completed_at DESC"
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS idx_items_id_text ON items ((CAST(id AS TEXT)))",
        "CREATE INDEX IF NOT EXISTS idx_item_worktrees_branch_history "
        "ON item_worktrees(branch)",
        "CREATE INDEX IF NOT EXISTS idx_item_worktrees_path_history "
        "ON item_worktrees(path)",
        "CREATE INDEX IF NOT EXISTS idx_epic_tasks_worktree "
        "ON epic_tasks(item_worktree_id)",
        "CREATE INDEX IF NOT EXISTS idx_deployment_runs_live_driver "
        "ON deployment_runs(id) WHERE driver_attachment IS NOT NULL "
        "AND driver_attachment <> '' AND status NOT IN ('cancelled','failed','succeeded')",
        "CREATE INDEX IF NOT EXISTS idx_harness_sessions_actor_machine "
        "ON harness_sessions(actor_id, machine_id)",
        "CREATE INDEX IF NOT EXISTS idx_qa_plan_executions_state_created "
        "ON qa_plan_executions(state, created_at, id)",
        "CREATE INDEX IF NOT EXISTS idx_shepherd_verdicts_ref_created "
        "ON shepherd_verdicts(public_ref, created_at DESC, id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_deployment_runs_project_environment_status "
        f"ON deployment_runs(project_id, target_environment_id, status, {completed_order}, id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_qa_requirements_member "
        "ON qa_requirements(deployment_member_item_id) "
        "WHERE deployment_member_item_id IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS idx_deployment_runs_project_activity "
        "ON deployment_runs(project_id, COALESCE(completed_at, created_at) DESC)",
        "CREATE INDEX IF NOT EXISTS idx_session_launches_project_item_origin "
        "ON session_launches(project_id, item_id, origin, created_at DESC, launch_id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_session_launches_project_result_completed "
        "ON session_launches(project_id, result_code, completed_at DESC, launch_id)",
        "CREATE INDEX IF NOT EXISTS idx_session_launch_attempts_open_batch "
        "ON session_launch_attempts(batch_id, started_at, relay_id) WHERE completed_at IS NULL",
        "CREATE INDEX IF NOT EXISTS idx_qa_plan_executions_run_state "
        "ON qa_plan_executions(deployment_run_id, state, created_at DESC, id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_session_messages_uncancelled_expiry "
        "ON session_messages(expires_at) WHERE cancelled_at IS NULL",
        "CREATE INDEX IF NOT EXISTS idx_item_worktrees_unreleased "
        "ON item_worktrees(item_id, id) WHERE released_at IS NULL",
        "CREATE INDEX IF NOT EXISTS idx_work_claims_active_order "
        "ON work_claims(claimed_at, id) WHERE released_at IS NULL",
        "CREATE INDEX IF NOT EXISTS idx_session_messages_sender_session "
        "ON session_messages(sender_session_id, created_at DESC, message_id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_session_messages_live_launch "
        f"ON session_messages (({launch})) "
        "WHERE cancelled_at IS NULL",
        "CREATE INDEX IF NOT EXISTS idx_session_launches_native_session "
        "ON session_launches(native_session_id)",
    ):
        conn.execute(statement)
    if connection_is_postgres(conn):
        # Root discovery uses PostgreSQL regular expressions and must include
        # released lanes: their checkouts remain workspace authority.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_item_worktrees_recorded_root "
            "ON item_worktrees ((COALESCE(NULLIF(substring(btrim(path) FROM "
            "'^(.*)/[.]worktrees(?:/.*)?$'), ''), '/'))) INCLUDE (path) "
            "WHERE btrim(path) ~ '^.*/[.]worktrees(?:/.*)?$'"
        )
