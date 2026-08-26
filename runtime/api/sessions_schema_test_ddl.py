"""Shared session, work-claim, tool-call, and coordination-lease fixture DDL.

Split from ``runtime.api.test_sessions`` (350-line authored cap). Both
``_create_schema`` and ``_create_ownership_schema`` embed this one
definition.
"""

_SESSIONS_AND_CLAIMS_DDL = """
        CREATE TABLE IF NOT EXISTS harness_sessions (
            session_id TEXT PRIMARY KEY,
            executor TEXT NOT NULL,
            executor_surface TEXT DEFAULT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            execution_lane TEXT NOT NULL DEFAULT 'primary',
            executor_version TEXT, machine_id TEXT,
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
            last_checkpoint_at TEXT DEFAULT NULL,
            native_thread_id TEXT DEFAULT NULL
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
    target_kind TEXT NOT NULL CONSTRAINT work_claims_target_kind_check
      CHECK(target_kind IN ('item','epic_task','process','steering_scope')),
    item_id INTEGER,
    epic_id INTEGER,
    task_num INTEGER,
    process_key TEXT,
    conflict_group TEXT,
    steering_project_id INTEGER,
    steering_strategy_doc_slugs TEXT,
    owner_kind TEXT,
    owner_item_id INTEGER,
    owner_session_id TEXT,
    owner_work_claim_id INTEGER,
    registered_by_actor_id INTEGER,
    registered_by_session_id TEXT,
    claim_type TEXT NOT NULL DEFAULT 'exclusive' CHECK(claim_type='exclusive'),
    claimed_at TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL,
    released_at TEXT,
    release_reason TEXT CHECK(release_reason IS NULL OR release_reason IN ('completed','released','reclaimed','handed_off','expired','session_ended')),
    reason TEXT DEFAULT NULL,
    reason_intent TEXT DEFAULT NULL,
    release_reason_intent TEXT DEFAULT NULL,
    CONSTRAINT work_claims_target_shape_check CHECK (
      (target_kind='item' AND item_id IS NOT NULL AND epic_id IS NULL AND task_num IS NULL AND process_key IS NULL AND conflict_group IS NULL AND steering_project_id IS NULL AND steering_strategy_doc_slugs IS NULL) OR
      (target_kind='epic_task' AND item_id IS NULL AND epic_id IS NOT NULL AND task_num IS NOT NULL AND process_key IS NULL AND conflict_group IS NULL AND steering_project_id IS NULL AND steering_strategy_doc_slugs IS NULL) OR
      (target_kind='process' AND item_id IS NULL AND epic_id IS NULL AND task_num IS NULL AND process_key IS NOT NULL AND conflict_group IS NOT NULL AND steering_project_id IS NULL AND steering_strategy_doc_slugs IS NULL) OR
      (target_kind='steering_scope' AND item_id IS NULL AND epic_id IS NULL AND task_num IS NULL AND process_key IS NULL AND conflict_group IS NULL AND steering_project_id IS NOT NULL AND steering_strategy_doc_slugs IS NOT NULL)
    ),
    CONSTRAINT work_claims_owner_shape_check CHECK (
      (target_kind<>'steering_scope' AND owner_kind IS NULL AND owner_item_id IS NULL AND owner_session_id IS NULL AND owner_work_claim_id IS NULL AND registered_by_actor_id IS NULL AND registered_by_session_id IS NULL) OR
      (target_kind='steering_scope' AND owner_kind='session' AND owner_item_id IS NULL AND owner_session_id=session_id AND owner_work_claim_id IS NULL AND registered_by_actor_id IS NOT NULL AND registered_by_session_id IS NOT NULL)
    ),
    FOREIGN KEY (session_id) REFERENCES harness_sessions(session_id)
);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_work_claims_active_item
            ON work_claims(item_id)
            WHERE released_at IS NULL AND target_kind='item';
        CREATE UNIQUE INDEX IF NOT EXISTS idx_work_claims_active_epic_task
            ON work_claims(epic_id, task_num)
            WHERE released_at IS NULL AND target_kind='epic_task';
        CREATE UNIQUE INDEX IF NOT EXISTS idx_work_claims_active_steering_scope_identity
            ON work_claims(steering_project_id, steering_strategy_doc_slugs)
            WHERE released_at IS NULL AND target_kind='steering_scope';
        CREATE INDEX IF NOT EXISTS idx_work_claims_steering_project_active
            ON work_claims(steering_project_id)
            WHERE released_at IS NULL AND target_kind='steering_scope';
        CREATE INDEX IF NOT EXISTS idx_work_claims_owner_session
            ON work_claims(owner_session_id)
            WHERE owner_session_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_work_claims_registered_by_actor
            ON work_claims(registered_by_actor_id)
            WHERE registered_by_actor_id IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_work_claims_active_process_conflict
            ON work_claims(conflict_group)
            WHERE released_at IS NULL AND target_kind='process';
        CREATE TABLE IF NOT EXISTS coordination_leases (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            lease_key TEXT NOT NULL,
            session_id TEXT NOT NULL,
            actor_id TEXT,
            acquired_at TEXT NOT NULL,
            heartbeat_at TEXT,
            released_at TEXT,
            release_reason TEXT,
            owner_kind TEXT NOT NULL DEFAULT 'session',
            owner_item_id INTEGER,
            owner_session_id TEXT,
            owner_work_claim_id INTEGER,
            released_by_session_id TEXT,
            released_by_actor_id TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_coordination_leases_live
            ON coordination_leases(project_id, lease_key)
            WHERE released_at IS NULL;
        CREATE INDEX IF NOT EXISTS idx_coordination_leases_session
            ON coordination_leases(session_id);
"""
