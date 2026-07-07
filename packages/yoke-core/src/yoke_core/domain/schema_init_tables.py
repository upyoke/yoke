"""Core table DDL for schema initialization."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_checks import (
    _VALID_ITEM_STATUSES_SQL,
    _VALID_TASK_STATUSES_SQL,
)
from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.domain.schema_init_path_integrity_tables import (
    create_path_integrity_tables,
)
from yoke_core.domain.schema_init_path_tables import create_path_registry_tables
from yoke_core.domain.schema_init_tables_sessions import create_session_tables
from yoke_core.domain.function_call_ledger import FUNCTION_CALL_LEDGER_CREATE_SQL
from yoke_core.domain.items_constants import DEFAULT_ITEM_ACTOR_ID
from yoke_core.domain.projects_restart_schema import _projects_table_sql
from yoke_core.domain.strategy_docs import STRATEGY_DOCS_CREATE_TABLE_SQL


def create_core_tables(conn: Any) -> None:
    execute_schema_script(conn, f"""
        {_projects_table_sql(if_not_exists=True)}
        CREATE TABLE IF NOT EXISTS items (
          id INTEGER PRIMARY KEY,
          title TEXT NOT NULL,
          type TEXT NOT NULL DEFAULT 'issue' CHECK(type IN ('epic','issue')),
          status TEXT NOT NULL DEFAULT 'idea' CHECK(status IN ({_VALID_ITEM_STATUSES_SQL})),
          priority TEXT NOT NULL DEFAULT 'medium' CHECK(priority IN ('high','medium','low')),
          flow TEXT DEFAULT 'accelerated',
          rework_count INTEGER DEFAULT 0,
          frozen INTEGER DEFAULT 0 CHECK(frozen IN (0,1)),
          blocked INTEGER DEFAULT 0 CHECK(blocked IN (0,1)),
          blocked_reason TEXT,
          github_issue TEXT,
          deployed_to TEXT,
          -- issue-only by convention; epic worktrees live on epic_dispatch_chains.worktree.
          -- "Active worktree for session+item" reads route through
          -- path_claim_active_claim_lookup._resolve_active_worktree.
          worktree TEXT,
          merged_at TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          source TEXT NOT NULL DEFAULT '{DEFAULT_ITEM_ACTOR_ID}',
          project_id INTEGER NOT NULL DEFAULT 1 REFERENCES projects(id),
          project_sequence INTEGER NOT NULL,
          spec_updated_at TEXT,
          spec_updated_by TEXT,
          UNIQUE(project_id, project_sequence)
        );
        CREATE TABLE IF NOT EXISTS ouroboros_entries (
          id INTEGER PRIMARY KEY,
          timestamp TEXT NOT NULL,
          agent TEXT NOT NULL,
          context TEXT,
          category TEXT NOT NULL,
          body TEXT NOT NULL,
          reviewed_at TEXT,
          archived_at TEXT,
          created_at TEXT NOT NULL,
          project_id INTEGER DEFAULT NULL REFERENCES projects(id)
        );
        CREATE TABLE IF NOT EXISTS wrapup_reports (
          id INTEGER PRIMARY KEY,
          session_timestamp TEXT NOT NULL UNIQUE,
          body TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        -- durable bounded carry-forward for Strategize landed-work review:
        -- one row per (project_id, item_id) ever seen as landed. `state`
        -- tracks reflected-in-SML / dismissed / pending; row presence is
        -- what makes a pending item survive deferred Strategize sessions.
        CREATE TABLE IF NOT EXISTS strategize_landed_carry (
          item_id INTEGER NOT NULL,
          project_id INTEGER NOT NULL REFERENCES projects(id),
          state TEXT NOT NULL DEFAULT 'pending'
            CHECK(state IN ('pending', 'reflected', 'dismissed')),
          first_seen_at TEXT NOT NULL,
          last_updated_at TEXT NOT NULL,
          last_session_id TEXT,
          reason TEXT,
          PRIMARY KEY (project_id, item_id)
        );
        CREATE INDEX IF NOT EXISTS idx_strategize_landed_carry_state
          ON strategize_landed_carry(project_id, state);
        -- item/task status transition history, written at mutation time by
        -- every status writer (yoke_core.domain.item_status_transitions).
        -- task_num NULL = item-level transition; non-null = epic-task
        -- transition with item_id = the parent epic's item id.
        CREATE TABLE IF NOT EXISTS item_status_transitions (
          id INTEGER PRIMARY KEY,
          item_id INTEGER NOT NULL,
          task_num INTEGER,
          from_status TEXT,
          to_status TEXT NOT NULL,
          source TEXT,
          session_id TEXT,
          actor_id INTEGER,
          project_id INTEGER,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_item_status_transitions_item_created
          ON item_status_transitions(item_id, created_at);
        -- board activity rollup: one row per (project, item, UTC day) of
        -- real domain mutation (yoke_core.domain.item_activity);
        -- MAX(id) is the board cache's monotonic invalidation watermark.
        CREATE TABLE IF NOT EXISTS item_activity_days (
          id INTEGER PRIMARY KEY,
          project_id INTEGER NOT NULL,
          item_id INTEGER NOT NULL,
          day TEXT NOT NULL,
          UNIQUE(project_id, item_id, day)
        );
        -- strategize / drift-review completion anchors per project
        -- (strategy_checkpoints.py); MAX(created_at) bounds delta windows.
        CREATE TABLE IF NOT EXISTS strategy_checkpoints (
          id INTEGER PRIMARY KEY,
          project_id INTEGER NOT NULL,
          kind TEXT NOT NULL CHECK(kind IN ('strategize', 'drift_review')),
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_strategy_checkpoints_project_created
          ON strategy_checkpoints(project_id, created_at);
        -- per-project strategy-doc authority; rendered views live at each
        -- project's .yoke/strategy/ (yoke_core.domain.strategy_docs).
        {STRATEGY_DOCS_CREATE_TABLE_SQL};
        -- dispatcher idempotency dedup store (function_call_ledger.py DDL).
        {FUNCTION_CALL_LEDGER_CREATE_SQL};
        CREATE TABLE IF NOT EXISTS release_entries (
          id INTEGER PRIMARY KEY,
          item_id INTEGER NOT NULL,
          category TEXT NOT NULL DEFAULT 'improvements' CHECK(category IN ('features','improvements','bug_fixes','internal')),
          title TEXT NOT NULL,
          version TEXT NOT NULL,
          project_id INTEGER NOT NULL DEFAULT 1 REFERENCES projects(id),
          created_at TEXT NOT NULL,
          UNIQUE(item_id, version, project_id)
        );
        CREATE TABLE IF NOT EXISTS epic_tasks (
          id INTEGER PRIMARY KEY,
          epic_id INTEGER NOT NULL,
          task_num INTEGER NOT NULL,
          title TEXT,
          worktree TEXT,
          context_estimate TEXT,
          dependencies TEXT,
          status TEXT DEFAULT 'planning' CHECK(status IN ({_VALID_TASK_STATUSES_SQL})),
          dispatch_attempts INTEGER DEFAULT 0,
          UNIQUE(epic_id, task_num)
        );
        CREATE TABLE IF NOT EXISTS epic_task_files (
          id INTEGER PRIMARY KEY,
          epic_id INTEGER NOT NULL,
          task_num INTEGER NOT NULL,
          file_path TEXT NOT NULL,
          action TEXT,
          UNIQUE(epic_id, task_num, file_path),
          FOREIGN KEY (epic_id, task_num) REFERENCES epic_tasks(epic_id, task_num)
        );
        CREATE TABLE IF NOT EXISTS epic_dispatch_chains (
          id INTEGER PRIMARY KEY,
          epic_id INTEGER NOT NULL,
          worktree TEXT NOT NULL,
          worktree_path TEXT,
          queue TEXT,
          current_index INTEGER DEFAULT 0,
          current_task TEXT,
          current_attempt INTEGER DEFAULT 1,
          max_attempts INTEGER DEFAULT 5,
          no_chain INTEGER DEFAULT 0,
          started_at TEXT,
          last_updated TEXT,
          UNIQUE(epic_id, worktree)
        );
        CREATE TABLE IF NOT EXISTS epic_progress_notes (
          id INTEGER PRIMARY KEY,
          epic_id INTEGER NOT NULL,
          task_num INTEGER NOT NULL,
          note_num INTEGER NOT NULL,
          body TEXT,
          commit_hash TEXT,
          synced_to_github INTEGER DEFAULT 0,
          created_at TEXT NOT NULL,
          UNIQUE(epic_id, task_num, note_num)
        );
        CREATE TABLE IF NOT EXISTS qa_requirements (
          id INTEGER PRIMARY KEY,
          item_id INTEGER,
          epic_id INTEGER,
          task_num INTEGER,
          deployment_run_id TEXT,
          qa_kind TEXT NOT NULL,
          qa_phase TEXT NOT NULL CHECK(qa_phase IN ('verification','post_deploy','manual_acceptance')),
          target_env TEXT,
          blocking_mode TEXT NOT NULL DEFAULT 'blocking' CHECK(blocking_mode IN ('blocking','non_blocking')),
          requirement_source TEXT NOT NULL DEFAULT 'explicit' CHECK(requirement_source IN ('explicit','seeded_default','ac_derived','flow_derived')),
          success_policy TEXT,
          capability_requirements TEXT,
          suite_id TEXT,
          waived_at TEXT,
          waiver_rationale TEXT,
          waiver_source TEXT,
          created_at TEXT NOT NULL,
          CHECK (
            (item_id IS NOT NULL AND epic_id IS NULL AND task_num IS NULL AND deployment_run_id IS NULL) OR
            (item_id IS NULL AND epic_id IS NOT NULL AND task_num IS NOT NULL AND deployment_run_id IS NULL) OR
            (item_id IS NULL AND epic_id IS NULL AND task_num IS NULL AND deployment_run_id IS NOT NULL)
          )
        );
        CREATE INDEX IF NOT EXISTS idx_qa_requirements_item ON qa_requirements(item_id);
        CREATE INDEX IF NOT EXISTS idx_qa_requirements_epic ON qa_requirements(epic_id, task_num);
        CREATE INDEX IF NOT EXISTS idx_qa_requirements_deployment ON qa_requirements(deployment_run_id);
        CREATE TABLE IF NOT EXISTS qa_runs (
          id INTEGER PRIMARY KEY,
          qa_requirement_id INTEGER NOT NULL,
          executor_type TEXT NOT NULL,
          qa_kind TEXT NOT NULL,
          verdict TEXT CHECK(verdict IN ('pass','fail','inconclusive','error')),
          execution_status TEXT CHECK(execution_status IN ('captured','capture_failed') OR execution_status IS NULL),
          score REAL,
          confidence REAL,
          raw_result TEXT, -- → JSONB on Postgres
          duration_ms INTEGER,
          started_at TEXT,
          completed_at TEXT,
          created_at TEXT NOT NULL,
          FOREIGN KEY (qa_requirement_id) REFERENCES qa_requirements(id)
        );
        CREATE INDEX IF NOT EXISTS idx_qa_runs_requirement ON qa_runs(qa_requirement_id);
        CREATE TABLE IF NOT EXISTS qa_artifacts (
          id INTEGER PRIMARY KEY,
          qa_run_id INTEGER,
          artifact_type TEXT NOT NULL,
          content_type TEXT,
          artifact_handle TEXT,
          metadata TEXT, -- → JSONB on Postgres
          created_at TEXT NOT NULL,
          FOREIGN KEY (qa_run_id) REFERENCES qa_runs(id)
        );
        CREATE INDEX IF NOT EXISTS idx_qa_artifacts_run ON qa_artifacts(qa_run_id);
        CREATE TABLE IF NOT EXISTS merge_locks (
          id INTEGER PRIMARY KEY,
          session_id TEXT NOT NULL,
          branch TEXT NOT NULL,
          epic_id TEXT,
          acquired_at TEXT NOT NULL,
          expires_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS item_sections (
          item_id INTEGER NOT NULL,
          section_name TEXT NOT NULL,
          content TEXT,
          ordering INTEGER,
          source TEXT NOT NULL DEFAULT 'operator',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY (item_id, section_name)
        );
    """)
    create_session_tables(conn)

def create_governed_tables(conn: Any) -> None:
    from yoke_core.domain.migration_audit_schema import ensure_migration_audit_table
    ensure_migration_audit_table(conn)

    # coordination_leases — shared-operation lease primitive keyed on
    # (project_id, lease_key).  The migration consumer scopes per-model
    # via ``LIVE_DB_MIGRATION:<model_name>``; future shared-operation
    # consumers pick their own key conventions without adding another
    # lock table.  Ordinary work ownership remains in ``work_claims``;
    # repo mutation authority remains in ``path_claims``.
    execute_schema_script(conn, """
        CREATE TABLE IF NOT EXISTS coordination_leases (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            lease_key TEXT NOT NULL,
            session_id TEXT NOT NULL,
            actor_id TEXT,
            acquired_at TEXT NOT NULL,
            heartbeat_at TEXT,
            released_at TEXT,
            release_reason TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS
            idx_coordination_leases_live ON coordination_leases(project_id, lease_key)
            WHERE released_at IS NULL;
        CREATE INDEX IF NOT EXISTS
            idx_coordination_leases_session ON coordination_leases(session_id);
        CREATE INDEX IF NOT EXISTS
            idx_coordination_leases_heartbeat ON coordination_leases(heartbeat_at);
    """)
    conn.commit()
