"""Idempotent schema-column and data-shape migrations."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.qa_schema import _migrate_qa_vocab
from yoke_core.domain.schema_checks import _validate_epic_task_statuses, _validate_item_statuses
from yoke_core.domain.schema_common import _add_column_if_not_exists, _column_exists, _table_exists
from yoke_core.domain.schema_migrations import _migrate_qa_execution_status
from yoke_core.domain.items_constants import DEFAULT_ITEM_ACTOR_ID


def apply_harness_session_columns(conn: Any) -> None:
    # Idempotent ADD COLUMN migrations for harness_sessions attribution
    _add_column_if_not_exists(conn, "harness_sessions", "current_item_id", "TEXT DEFAULT NULL")
    _add_column_if_not_exists(conn, "harness_sessions", "current_item_set_at", "TEXT DEFAULT NULL")
    _add_column_if_not_exists(conn, "harness_sessions", "recent_item_id", "TEXT DEFAULT NULL")
    _add_column_if_not_exists(conn, "harness_sessions", "recent_item_status", "TEXT DEFAULT NULL")
    _add_column_if_not_exists(conn, "harness_sessions", "recent_item_recorded_at", "TEXT DEFAULT NULL")
    # actor_id binds a live session to its accountable subject. Nullable
    # at the column level so migration apply can land before backfill;
    # session-creation paths in :mod:`sessions_offer` require non-null
    # on new writes.
    _add_column_if_not_exists(conn, "harness_sessions", "actor_id", "INTEGER DEFAULT NULL")
    _add_column_if_not_exists(conn, "harness_sessions", "last_seen_main_sha", "TEXT DEFAULT NULL")
    _add_column_if_not_exists(conn, "harness_sessions", "last_drift_check_at", "TEXT DEFAULT NULL")
    # executor_display_name carries the surface-specific alias
    # (claude-desktop / codex-vscode / etc.) when the canonical executor
    # value loses that information. Nullable so historical rows that came
    # in canonical-only stay clean.
    _add_column_if_not_exists(conn, "harness_sessions", "executor_display_name", "TEXT DEFAULT NULL")
    # session-activity state: tool-call liveness and episode boundary
    # are first-class columns (the events ledger is telemetry-only).
    _add_column_if_not_exists(conn, "harness_sessions", "last_tool_call_at", "TEXT DEFAULT NULL")
    _add_column_if_not_exists(conn, "harness_sessions", "tool_call_count", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_not_exists(conn, "harness_sessions", "episode_started_at", "TEXT DEFAULT NULL")
    _add_column_if_not_exists(conn, "harness_sessions", "pending_resume_notice", "TEXT DEFAULT NULL")
    # chain-checkpoint state: progress survives offer-envelope rewrites.
    _add_column_if_not_exists(conn, "harness_sessions", "last_chain_step", "INTEGER DEFAULT NULL")
    _add_column_if_not_exists(conn, "harness_sessions", "last_checkpoint_at", "TEXT DEFAULT NULL")
    conn.commit()


def apply_idempotent_migrations(conn: Any) -> None:
    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"

    # Idempotent ADD COLUMN migrations for epic_tasks
    _add_column_if_not_exists(conn, "epic_tasks", "body", "TEXT")
    _add_column_if_not_exists(conn, "epic_tasks", "github_issue", "TEXT")
    _add_column_if_not_exists(conn, "epic_tasks", "branch", "TEXT")
    _add_column_if_not_exists(conn, "epic_tasks", "worktree_path", "TEXT")
    _add_column_if_not_exists(conn, "epic_tasks", "blocked_by", "TEXT")
    _add_column_if_not_exists(conn, "epic_tasks", "max_attempts", "INTEGER DEFAULT 5")
    _add_column_if_not_exists(conn, "epic_tasks", "agent_id", "TEXT")
    _add_column_if_not_exists(conn, "epic_tasks", "last_heartbeat", "TEXT")
    # task-freshness state: stamped by every epic-task mutation surface.
    _add_column_if_not_exists(conn, "epic_tasks", "last_activity_at", "TEXT")
    conn.commit()

    # Per-project GitHub sync switch. NULL resolves to 'enabled' through
    # yoke_core.domain.projects_github_sync_mode; 'backlog_only' turns off
    # every backlog->GitHub issue sync surface for the project.
    _add_column_if_not_exists(conn, "projects", "github_sync_mode", "TEXT DEFAULT NULL")
    conn.commit()

    # claim-reason / release-intent state (the events ledger is
    # telemetry-only; acquire/release paths stamp these columns).
    _add_column_if_not_exists(conn, "work_claims", "reason", "TEXT DEFAULT NULL")
    _add_column_if_not_exists(conn, "work_claims", "reason_intent", "TEXT DEFAULT NULL")
    _add_column_if_not_exists(conn, "work_claims", "release_reason_intent", "TEXT DEFAULT NULL")
    conn.commit()

    # items.source stores the stringified actors.id for the item originator.
    _add_column_if_not_exists(
        conn,
        "items",
        "source",
        f"TEXT NOT NULL DEFAULT '{DEFAULT_ITEM_ACTOR_ID}'",
    )
    conn.execute(
        f"UPDATE items SET source = {placeholder} WHERE source IS NULL",
        (DEFAULT_ITEM_ACTOR_ID,),
    )
    conn.commit()

    # Numeric project authority for items.
    _add_column_if_not_exists(conn, "items", "project_id", "INTEGER NOT NULL DEFAULT 1")
    _add_column_if_not_exists(conn, "items", "project_sequence", "INTEGER")
    conn.execute(
        "UPDATE items SET project_sequence = id WHERE project_sequence IS NULL"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_items_project_sequence "
        "ON items(project_id, project_sequence)"
    )
    conn.commit()

    # Add deployment_flow and deploy_stage columns
    _add_column_if_not_exists(conn, "items", "deployment_flow", "TEXT")
    _add_column_if_not_exists(conn, "items", "deploy_stage", "TEXT")
    conn.commit()

    # Add numeric project authority to ouroboros_entries.
    _add_column_if_not_exists(conn, "ouroboros_entries", "project_id", "INTEGER DEFAULT NULL")
    conn.commit()

    # Add project column to release_entries
    _add_column_if_not_exists(conn, "release_entries", "project_id", "INTEGER NOT NULL DEFAULT 1")
    conn.commit()

    # Drop legacy epic_reviews table
    if _table_exists(conn, "epic_reviews"):
        conn.execute("DROP TABLE IF EXISTS epic_reviews")
        conn.commit()
        print("Dropped legacy epic_reviews table (consolidated into reviews).")

    # owner — actor FK companion to items.source. Nullable here because
    # the one-shot migration backfills it during the source/owner
    # conversion; new write paths in :mod:`backlog_create_op` resolve
    # both to non-null actor IDs. The column type stays
    # TEXT to preserve historical source/owner values; readers cast to
    # int at the boundary.
    _add_column_if_not_exists(conn, "items", "owner", "TEXT")

    # Add structured columns to items table
    _add_column_if_not_exists(conn, "items", "spec", "TEXT")
    _add_column_if_not_exists(conn, "items", "design_spec", "TEXT")
    _add_column_if_not_exists(conn, "items", "technical_plan", "TEXT")
    _add_column_if_not_exists(conn, "items", "worktree_plan", "TEXT")
    _add_column_if_not_exists(conn, "items", "shepherd_log", "TEXT")
    _add_column_if_not_exists(conn, "items", "shepherd_caveats", "TEXT")
    _add_column_if_not_exists(conn, "items", "test_results", "TEXT")
    _add_column_if_not_exists(conn, "items", "deploy_log", "TEXT")
    conn.commit()

    # browser_qa_metadata — JSON-valued structured field populated at
    # idea/refine time.  Annotated for Postgres cutover; see
    # :data:`yoke_core.domain.sql_json.JSONB_COLUMNS`.  Every existing
    # row is populated with the explicit negative default on first
    # migration so seeding callers never encounter NULL/'null' metadata.
    _add_column_if_not_exists(conn, "items", "browser_qa_metadata", "TEXT")  # → JSONB on Postgres
    from yoke_core.domain.browser_qa_metadata import NEGATIVE_DEFAULT_JSON
    conn.execute(
        f"UPDATE items SET browser_qa_metadata = {placeholder} "
        "WHERE browser_qa_metadata IS NULL "
        "OR browser_qa_metadata = '' "
        "OR browser_qa_metadata = 'null'",
        (NEGATIVE_DEFAULT_JSON,),
    )
    conn.commit()

    # db_mutation_profile / db_compatibility_attestation — governed
    # DB-mutation contract (governed DB-mutation contract).  DB-level NOT NULL DEFAULT makes
    # omission structurally impossible: every INSERT lands a row with a
    # valid negative default.  Annotated for Postgres cutover; see
    # :data:`yoke_core.domain.sql_json.JSONB_COLUMNS`.  Existing rows
    # are backfilled with the explicit negative defaults.
    _add_column_if_not_exists(
        conn, "items", "db_mutation_profile",
        "TEXT NOT NULL DEFAULT '{\"state\":\"none\"}'",  # → JSONB on Postgres
    )
    _add_column_if_not_exists(
        conn, "items", "db_compatibility_attestation",
        "TEXT NOT NULL DEFAULT '{}'",  # → JSONB on Postgres
    )
    from yoke_core.domain.db_mutation_profile import (
        NEGATIVE_DEFAULT_JSON as _DMP_NEG,
    )
    from yoke_core.domain.db_compatibility_attestation import (
        NEGATIVE_DEFAULT_JSON as _DCA_NEG,
    )
    conn.execute(
        f"UPDATE items SET db_mutation_profile = {placeholder} "
        "WHERE db_mutation_profile IS NULL "
        "OR db_mutation_profile = '' "
        "OR db_mutation_profile = 'null'",
        (_DMP_NEG,),
    )
    conn.execute(
        f"UPDATE items SET db_compatibility_attestation = {placeholder} "
        "WHERE db_compatibility_attestation IS NULL "
        "OR db_compatibility_attestation = '' "
        "OR db_compatibility_attestation = 'null'",
        (_DCA_NEG,),
    )
    conn.commit()

    # github_body_compact_pending — nullable ISO timestamp set when the
    # last successful GitHub body sync landed the compact mirror (body
    # over budget) and cleared when a full-body sync lands. The repair
    # pass (backfill-oversized-bodies) reads it as its candidate queue;
    # owner: yoke_core.domain.backlog_github_body_budget.
    _add_column_if_not_exists(
        conn, "items", "github_body_compact_pending", "TEXT",
    )
    conn.commit()

    # architecture_impact — operator-authored enum classifying the item's
    # relationship to the project architecture model. Default 'none' so
    # pre-existing rows treat as "no architectural impact"; refine /
    # idea_readiness_check escalates 'uncertain' rows.
    _add_column_if_not_exists(
        conn, "items", "architecture_impact",
        "TEXT NOT NULL DEFAULT 'none'",
    )
    conn.execute(
        "UPDATE items SET architecture_impact = 'none' "
        "WHERE architecture_impact IS NULL "
        "OR architecture_impact = '' "
        "OR architecture_impact = 'null'"
    )
    conn.commit()

    # Add source column to item_sections
    _add_column_if_not_exists(conn, "item_sections", "source", "TEXT NOT NULL DEFAULT 'operator'")
    conn.commit()

    # Drop deprecated prd column if upgrading from an older schema
    if _column_exists(conn, "items", "prd"):
        conn.execute("ALTER TABLE items DROP COLUMN prd")
        conn.commit()
        print("Dropped deprecated 'prd' column from items table.")

    # Retire QA vocabulary
    _migrate_qa_vocab(conn)

    # Split browser capture from inspection verdict
    _migrate_qa_execution_status(conn)

    _validate_item_statuses(conn)
    _validate_epic_task_statuses(conn)
