"""Session/claims schema slice for fresh-install initialization.

Sibling of :mod:`schema_init_tables` (350-cap split): owns the
``harness_sessions`` + ``session_tool_calls`` + ``work_claims`` DDL.
Called from ``create_core_tables`` so install order is unchanged.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script


def create_session_tables(conn: Any) -> None:
    execute_schema_script(conn, """
        CREATE TABLE IF NOT EXISTS harness_sessions (
          session_id TEXT PRIMARY KEY,
          executor TEXT NOT NULL,
          executor_display_name TEXT DEFAULT NULL,
          provider TEXT NOT NULL,
          model TEXT NOT NULL,
          execution_lane TEXT NOT NULL DEFAULT 'primary',
          capabilities TEXT DEFAULT '[]',
          workspace TEXT NOT NULL,
          project_id INTEGER NOT NULL REFERENCES projects(id),
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
          last_seen_main_sha TEXT DEFAULT NULL,
          last_drift_check_at TEXT DEFAULT NULL,
          last_tool_call_at TEXT DEFAULT NULL,
          tool_call_count INTEGER NOT NULL DEFAULT 0,
          episode_started_at TEXT DEFAULT NULL,
          pending_resume_notice TEXT DEFAULT NULL,
          last_chain_step INTEGER DEFAULT NULL,
          last_checkpoint_at TEXT DEFAULT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_harness_sessions_lane ON harness_sessions(execution_lane);
        CREATE INDEX IF NOT EXISTS idx_harness_sessions_heartbeat ON harness_sessions(last_heartbeat);
        CREATE INDEX IF NOT EXISTS idx_harness_sessions_project ON harness_sessions(project_id);
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
        CREATE INDEX IF NOT EXISTS idx_session_tool_calls_session_started
          ON session_tool_calls(session_id, started_at);
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
        CREATE INDEX IF NOT EXISTS idx_work_claims_session ON work_claims(session_id);
        CREATE INDEX IF NOT EXISTS idx_work_claims_session_released
          ON work_claims(session_id, released_at);
        CREATE INDEX IF NOT EXISTS idx_work_claims_item ON work_claims(item_id);
        CREATE INDEX IF NOT EXISTS idx_work_claims_epic_task ON work_claims(epic_id, task_num);
        CREATE INDEX IF NOT EXISTS idx_work_claims_process ON work_claims(process_key);
        CREATE INDEX IF NOT EXISTS idx_work_claims_heartbeat ON work_claims(last_heartbeat);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_work_claims_active_process_conflict
          ON work_claims(conflict_group)
          WHERE released_at IS NULL AND target_kind='process';
    """)
