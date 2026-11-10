"""Index the selective reads on the session hook and launch paths."""


def apply(conn):
    """Build transactionally; replay preserves rows and existing indexes."""
    for statement in (
        "CREATE INDEX IF NOT EXISTS idx_item_worktrees_unreleased "
        "ON item_worktrees(item_id, id) WHERE released_at IS NULL",
        "CREATE INDEX IF NOT EXISTS idx_work_claims_active_order "
        "ON work_claims(claimed_at, id) WHERE released_at IS NULL",
        "CREATE INDEX IF NOT EXISTS idx_session_messages_sender_session "
        "ON session_messages(sender_session_id)",
        "CREATE INDEX IF NOT EXISTS idx_session_messages_live_launch "
        "ON session_messages ((NULLIF(selector_snapshot, '')::jsonb #>> '{launch_id}')) "
        "WHERE cancelled_at IS NULL",
        "CREATE INDEX IF NOT EXISTS idx_session_launches_native_session "
        "ON session_launches(native_session_id)",
    ):
        conn.execute(statement)
