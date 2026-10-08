"""Shared session, work-claim, and tool-call fixture DDL.

Split from ``runtime.api.test_sessions`` (350-line authored cap). Both
``_create_schema`` and ``_create_ownership_schema`` embed this one
definition.
"""

from yoke_core.domain.work_claim_target_sql import TARGET_KIND_CHECK_SQL
from yoke_core.domain.session_native_process_observation import (
    NATIVE_PROCESS_GONE_AT_COLUMN,
    NATIVE_PROCESS_GONE_EVIDENCE_COLUMN,
    NATIVE_PROCESS_EVIDENCE_COLUMN_DDL,
    NATIVE_PROCESS_INSTANT_COLUMN_DDL,
)

_SESSIONS_AND_CLAIMS_DDL = f"""
        CREATE TABLE IF NOT EXISTS harness_sessions (
            session_id TEXT PRIMARY KEY,
            executor TEXT NOT NULL,
            executor_surface TEXT DEFAULT NULL,
            provider TEXT NOT NULL,
            model TEXT,
            reasoning_effort TEXT DEFAULT NULL,
            context_window_tokens INTEGER DEFAULT NULL,
            usage_totals TEXT DEFAULT NULL,
            requested_model TEXT DEFAULT NULL,
            requested_reasoning_effort TEXT DEFAULT NULL,
            requested_context_window_tokens INTEGER DEFAULT NULL,
            execution_level TEXT NOT NULL DEFAULT 'primary',
            executor_version TEXT, machine_id TEXT,
            workspace TEXT NOT NULL,
            project_id INTEGER NOT NULL DEFAULT 1 REFERENCES projects(id),
            mode TEXT DEFAULT 'wait',
            quiet_reason TEXT DEFAULT NULL,
            keepalive_until TIMESTAMPTZ DEFAULT NULL,
            keepalive_reason TEXT DEFAULT NULL,
            offered_at TIMESTAMPTZ NOT NULL,
            last_heartbeat TIMESTAMPTZ NOT NULL,
            ended_at TIMESTAMPTZ,
            terminated_at TIMESTAMPTZ,
            terminated_by_actor_id INTEGER,
            terminated_by_session_id TEXT,
            termination_reason TEXT,
            offer_envelope TEXT,
            current_item_id TEXT DEFAULT NULL,
            current_item_set_at TIMESTAMPTZ DEFAULT NULL,
            recent_item_id TEXT DEFAULT NULL,
            recent_item_status TEXT DEFAULT NULL,
            recent_item_recorded_at TIMESTAMPTZ DEFAULT NULL,
            actor_id INTEGER DEFAULT NULL,
            last_tool_call_at TIMESTAMPTZ DEFAULT NULL,
            tool_call_count INTEGER NOT NULL DEFAULT 0,
            episode_started_at TIMESTAMPTZ DEFAULT NULL,
            {NATIVE_PROCESS_GONE_AT_COLUMN} {NATIVE_PROCESS_INSTANT_COLUMN_DDL},
            {NATIVE_PROCESS_GONE_EVIDENCE_COLUMN} {NATIVE_PROCESS_EVIDENCE_COLUMN_DDL},
            pending_resume_notice TEXT DEFAULT NULL,
            last_chain_step INTEGER DEFAULT NULL,
            last_checkpoint_at TIMESTAMPTZ DEFAULT NULL,
            native_thread_id TEXT DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS session_tool_calls (
            id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL,
            tool_use_id TEXT NOT NULL,
            tool_name TEXT,
            started_at TIMESTAMPTZ NOT NULL,
            completed_at TIMESTAMPTZ,
            outcome TEXT,
            command_summary TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_session_tool_calls_dedup
            ON session_tool_calls(session_id, tool_use_id);
        CREATE TABLE IF NOT EXISTS work_claims (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    target_kind TEXT NOT NULL CONSTRAINT work_claims_target_kind_check
      CHECK({TARGET_KIND_CHECK_SQL}),
    scope TEXT NOT NULL,
    claim_type TEXT NOT NULL DEFAULT 'exclusive' CHECK(claim_type='exclusive'),
    claimed_at TIMESTAMPTZ NOT NULL,
    last_heartbeat TIMESTAMPTZ NOT NULL,
    released_at TIMESTAMPTZ,
    release_reason TEXT CHECK(release_reason IS NULL OR release_reason IN ('completed','released','reclaimed','handed_off','expired','session_ended')),
    reason TEXT DEFAULT NULL,
    reason_intent TEXT DEFAULT NULL,
    release_reason_intent TEXT DEFAULT NULL,
    FOREIGN KEY (session_id) REFERENCES harness_sessions(session_id)
);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_work_claims_active_item
            ON work_claims(scope)
            WHERE released_at IS NULL AND target_kind='item';
        CREATE UNIQUE INDEX IF NOT EXISTS idx_work_claims_active_epic_task
            ON work_claims(scope)
            WHERE released_at IS NULL AND target_kind='epic_task';
        CREATE UNIQUE INDEX IF NOT EXISTS idx_work_claims_active_steering
            ON work_claims(scope)
            WHERE released_at IS NULL AND target_kind='steering';
        CREATE UNIQUE INDEX IF NOT EXISTS idx_work_claims_active_process_conflict
            ON work_claims(scope)
            WHERE released_at IS NULL AND target_kind='process';
        CREATE UNIQUE INDEX IF NOT EXISTS idx_work_claims_active_qa_admission
            ON work_claims(scope)
            WHERE released_at IS NULL AND target_kind='qa_admission';
        CREATE UNIQUE INDEX IF NOT EXISTS idx_work_claims_active_route_qualification
            ON work_claims(scope)
            WHERE released_at IS NULL AND target_kind='route_qualification';
        CREATE UNIQUE INDEX IF NOT EXISTS
            idx_work_claims_active_migration_serialization
            ON work_claims(
                ((scope::jsonb) ->> 'project_id'),
                ((scope::jsonb) ->> 'model')
            )
            WHERE released_at IS NULL AND target_kind='migration_serialization';
"""
