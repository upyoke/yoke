"""Shared harness_sessions + work_claims + session_tool_calls fixture DDL.

Split from ``runtime.api.test_sessions`` (350-line authored cap). Both
``_create_schema`` and ``_create_ownership_schema`` embed this one
definition.
"""

_SESSIONS_AND_CLAIMS_DDL = """
        CREATE TABLE IF NOT EXISTS harness_sessions (
            session_id TEXT PRIMARY KEY,
            executor TEXT NOT NULL,
            executor_display_name TEXT DEFAULT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            execution_lane TEXT NOT NULL DEFAULT 'primary',
            capabilities TEXT DEFAULT '[]',
            workspace TEXT NOT NULL,
            project_id INTEGER NOT NULL DEFAULT 1 REFERENCES projects(id),
            mode TEXT DEFAULT 'wait',
            offered_at TEXT NOT NULL,
            last_heartbeat TEXT NOT NULL,
            ended_at TEXT,
            offer_envelope TEXT,
            current_item_id TEXT DEFAULT NULL,
            current_item_set_at TEXT DEFAULT NULL,
            recent_item_id TEXT DEFAULT NULL,
            recent_item_status TEXT DEFAULT NULL,
            recent_item_recorded_at TEXT DEFAULT NULL,
            actor_id INTEGER DEFAULT NULL,
            last_tool_call_at TEXT DEFAULT NULL,
            tool_call_count INTEGER NOT NULL DEFAULT 0,
            episode_started_at TEXT DEFAULT NULL,
            pending_resume_notice TEXT DEFAULT NULL,
            last_chain_step INTEGER DEFAULT NULL,
            last_checkpoint_at TEXT DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS session_tool_calls (
            id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL,
            tool_use_id TEXT NOT NULL,
            tool_name TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            outcome TEXT,
            command_summary TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_session_tool_calls_dedup
            ON session_tool_calls(session_id, tool_use_id);
        CREATE TABLE IF NOT EXISTS work_claims (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('item','epic_task','process')),
    item_id INTEGER,
    epic_id INTEGER,
    task_num INTEGER,
    process_key TEXT,
    conflict_group TEXT,
    claim_type TEXT NOT NULL DEFAULT 'exclusive' CHECK(claim_type='exclusive'),
    claimed_at TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL,
    released_at TEXT,
    release_reason TEXT CHECK(release_reason IS NULL OR release_reason IN ('completed','released','reclaimed','handed_off','expired','session_ended')),
    reason TEXT DEFAULT NULL,
    reason_intent TEXT DEFAULT NULL,
    release_reason_intent TEXT DEFAULT NULL,
    CHECK (
      (target_kind='item' AND item_id IS NOT NULL AND epic_id IS NULL AND task_num IS NULL AND process_key IS NULL AND conflict_group IS NULL) OR
      (target_kind='epic_task' AND item_id IS NULL AND epic_id IS NOT NULL AND task_num IS NOT NULL AND process_key IS NULL AND conflict_group IS NULL) OR
      (target_kind='process' AND item_id IS NULL AND epic_id IS NULL AND task_num IS NULL AND process_key IS NOT NULL AND conflict_group IS NOT NULL)
    ),
    FOREIGN KEY (session_id) REFERENCES harness_sessions(session_id)
);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_work_claims_active_process_conflict
            ON work_claims(conflict_group)
            WHERE released_at IS NULL AND target_kind='process';
"""
