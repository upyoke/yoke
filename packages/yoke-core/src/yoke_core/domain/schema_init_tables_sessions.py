"""Session/claims schema slice for fresh-install initialization.

Sibling of :mod:`schema_init_tables` (350-cap split): owns the
``harness_sessions`` + ``session_tool_calls`` + ``work_claims`` DDL.
Called from ``create_core_tables`` so install order is unchanged.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.domain.session_turn_posture import (
    TURN_POSTURE_AT_COLUMN_DDL,
    TURN_POSTURE_COLUMN_DDL,
)
from yoke_contracts.executor_labels import (
    CANONICAL_HARNESS_IDS,
    KNOWN_SURFACE_LABELS,
)
from yoke_core.domain.work_claim_target_sql import TARGET_KIND_CHECK_SQL


def create_session_tables(conn: Any) -> None:
    executor_values = ", ".join(
        f"'{executor}'" for executor in sorted(CANONICAL_HARNESS_IDS)
    )
    surface_values = ", ".join(
        f"'{surface}'" for surface in sorted(KNOWN_SURFACE_LABELS)
    )
    execute_schema_script(
        conn,
        f"""
        CREATE TABLE IF NOT EXISTS harness_sessions (
          session_id TEXT PRIMARY KEY,
          executor TEXT NOT NULL CHECK(executor IN ({executor_values})),
          executor_surface TEXT DEFAULT NULL
            CHECK(executor_surface IS NULL OR executor_surface IN ({surface_values})),
          executor_version TEXT DEFAULT NULL,
          machine_id TEXT DEFAULT NULL,
          provider TEXT NOT NULL,
          model TEXT NOT NULL,
          execution_lane TEXT NOT NULL DEFAULT 'primary',
          workspace TEXT NOT NULL,
          project_id INTEGER NOT NULL REFERENCES projects(id),
          mode TEXT DEFAULT 'wait',
          parked_reason TEXT DEFAULT NULL,
          offered_at TEXT NOT NULL,
          last_heartbeat TEXT NOT NULL,
          turn_posture {TURN_POSTURE_COLUMN_DDL},
          turn_posture_at {TURN_POSTURE_AT_COLUMN_DDL},
          ended_at TEXT,
          terminated_at TEXT,
          terminated_by_actor_id INTEGER,
          terminated_by_session_id TEXT,
          termination_reason TEXT,
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
          target_kind TEXT NOT NULL CONSTRAINT work_claims_target_kind_check
            CHECK({TARGET_KIND_CHECK_SQL}),
          scope TEXT NOT NULL,
          claim_type TEXT NOT NULL DEFAULT 'exclusive' CHECK(claim_type='exclusive'),
          claimed_at TEXT NOT NULL,
          last_heartbeat TEXT NOT NULL,
          released_at TEXT,
          release_reason TEXT CHECK(release_reason IS NULL OR release_reason IN ('completed','released','reclaimed','handed_off','expired','session_ended')),
          reason TEXT DEFAULT NULL,
          reason_intent TEXT DEFAULT NULL,
          release_reason_intent TEXT DEFAULT NULL,
          FOREIGN KEY (session_id) REFERENCES harness_sessions(session_id)
        );
        CREATE INDEX IF NOT EXISTS idx_work_claims_session ON work_claims(session_id);
        CREATE INDEX IF NOT EXISTS idx_work_claims_session_released
          ON work_claims(session_id, released_at);
        CREATE INDEX IF NOT EXISTS idx_work_claims_heartbeat ON work_claims(last_heartbeat);
    """,
    )
