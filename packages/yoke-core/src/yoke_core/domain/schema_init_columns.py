"""Idempotent schema-column and data-shape migrations.

Two operation classes live here, split into two entry points so the boot
converge path can run the safe half without the destructive half:

* :func:`apply_additive_schema` — strictly additive DDL (``ADD COLUMN IF NOT
  EXISTS``, ``CREATE INDEX IF NOT EXISTS``). Structurally incapable of dropping
  or rewriting a row, so it is safe to run on every server boot of an
  already-born universe — the mechanism that propagates a newly-deployed
  additive column to existing prod / self-host universes.
* :func:`apply_legacy_data_migrations` — the birth/full-init-only tail: guarded
  destructive drops of retired surfaces, data backfills that normalize legacy
  rows, the qa-vocabulary rebuild, and the canonical-status validators. Never
  runs on the deploy/boot converge path.

:func:`apply_idempotent_migrations` runs both, in that order, and is retained as
the birth and test-fixture entry point so every existing caller is unchanged.
"""

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


def apply_additive_schema(conn: Any) -> None:
    """Strictly additive, idempotent schema convergence.

    Contains ONLY ``ADD COLUMN IF NOT EXISTS`` and ``CREATE INDEX IF NOT
    EXISTS`` — no ``DROP``, no data-backfill ``UPDATE``, no row rewrites. Safe to
    run on every server boot of an already-born universe (see
    :func:`yoke_core.domain.schema_init.converge_core_schema`), which is what
    propagates a newly-deployed additive column to existing prod / self-host
    universes whose last full ``cmd_init`` predates the column.

    Convergence invariant: this runs only against a universe already born via the
    full init chain, so every older column already exists and is populated. A new
    additive column MUST therefore be self-sufficient on ADD alone — nullable
    (NULL is a valid value) or ``NOT NULL DEFAULT`` (Postgres populates existing
    rows at ADD time). A column that needs a follow-up data backfill to be valid
    belongs in :func:`apply_legacy_data_migrations`, not here.
    """
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
    # NOT NULL DEFAULT populates existing rows at ADD time; the legacy-NULL
    # normalization lives in apply_legacy_data_migrations.
    _add_column_if_not_exists(
        conn,
        "items",
        "source",
        f"TEXT NOT NULL DEFAULT '{DEFAULT_ITEM_ACTOR_ID}'",
    )
    conn.commit()

    # Numeric project authority for items. project_id is self-sufficient
    # (NOT NULL DEFAULT populates existing rows at ADD time). project_sequence
    # has no DB default and needs an id-based backfill to be valid, so it, its
    # backfill, and its unique index live together in
    # apply_legacy_data_migrations (the birth/full-init path), never on this
    # additive converge path.
    _add_column_if_not_exists(conn, "items", "project_id", "INTEGER NOT NULL DEFAULT 1")
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
    # idea/refine time.  Added nullable; existing-row normalization to the
    # negative default lives in apply_legacy_data_migrations.  Annotated for
    # Postgres cutover; see :data:`yoke_core.domain.sql_json.JSONB_COLUMNS`.
    _add_column_if_not_exists(conn, "items", "browser_qa_metadata", "TEXT")  # → JSONB on Postgres
    conn.commit()

    # db_mutation_profile / db_compatibility_attestation — governed
    # DB-mutation contract.  DB-level NOT NULL DEFAULT makes omission
    # structurally impossible: every INSERT lands a row with a valid negative
    # default and existing rows populate at ADD time.  Annotated for Postgres
    # cutover; see :data:`yoke_core.domain.sql_json.JSONB_COLUMNS`.
    _add_column_if_not_exists(
        conn, "items", "db_mutation_profile",
        "TEXT NOT NULL DEFAULT '{\"state\":\"none\"}'",  # → JSONB on Postgres
    )
    _add_column_if_not_exists(
        conn, "items", "db_compatibility_attestation",
        "TEXT NOT NULL DEFAULT '{}'",  # → JSONB on Postgres
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
    # relationship to the project architecture model. NOT NULL DEFAULT 'none'
    # populates existing rows at ADD time; refine / idea_readiness_check
    # escalates 'uncertain' rows.
    _add_column_if_not_exists(
        conn, "items", "architecture_impact",
        "TEXT NOT NULL DEFAULT 'none'",
    )
    conn.commit()

    # Add source column to item_sections
    _add_column_if_not_exists(conn, "item_sections", "source", "TEXT NOT NULL DEFAULT 'operator'")
    conn.commit()


def apply_legacy_data_migrations(conn: Any) -> None:
    """Birth/full-init-only data-shape migrations and legacy drops.

    Runs ONLY from the full init chain (:func:`yoke_core.domain.schema_init.cmd_init`)
    and the schema fixtures — never on the boot converge path — because it
    performs the operations that are unsafe to run on every deploy: guarded
    destructive drops of retired surfaces, data backfills that normalize legacy
    NULL/'' rows, the qa-vocabulary table rebuild, and the canonical-status
    validators. Assumes :func:`apply_additive_schema` has already added every
    column these statements touch.
    """
    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"

    # items.source — normalize any legacy NULL row to the default actor.
    conn.execute(
        f"UPDATE items SET source = {placeholder} WHERE source IS NULL",
        (DEFAULT_ITEM_ACTOR_ID,),
    )
    conn.commit()

    # items.project_sequence — add the column, backfill it from the id, and
    # create its unique index. project_sequence has no DB default so its ADD is
    # not self-sufficient; the column, its backfill, and its unique index stay
    # co-located here (project_id is already present from apply_additive_schema).
    _add_column_if_not_exists(conn, "items", "project_sequence", "INTEGER")
    conn.execute(
        "UPDATE items SET project_sequence = id WHERE project_sequence IS NULL"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_items_project_sequence "
        "ON items(project_id, project_sequence)"
    )
    conn.commit()

    # Drop legacy epic_reviews table
    if _table_exists(conn, "epic_reviews"):
        conn.execute("DROP TABLE IF EXISTS epic_reviews")
        conn.commit()
        print("Dropped legacy epic_reviews table (consolidated into reviews).")

    # browser_qa_metadata — normalize legacy NULL/''/'null' rows to the
    # explicit negative default so seeding callers never encounter empty
    # metadata.
    from yoke_core.domain.browser_qa_metadata import NEGATIVE_DEFAULT_JSON
    conn.execute(
        f"UPDATE items SET browser_qa_metadata = {placeholder} "
        "WHERE browser_qa_metadata IS NULL "
        "OR browser_qa_metadata = '' "
        "OR browser_qa_metadata = 'null'",
        (NEGATIVE_DEFAULT_JSON,),
    )
    conn.commit()

    # db_mutation_profile / db_compatibility_attestation — normalize legacy
    # NULL/''/'null' rows to the explicit negative defaults.
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

    # architecture_impact — normalize legacy NULL/''/'null' rows to 'none'.
    conn.execute(
        "UPDATE items SET architecture_impact = 'none' "
        "WHERE architecture_impact IS NULL "
        "OR architecture_impact = '' "
        "OR architecture_impact = 'null'"
    )
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


def apply_idempotent_migrations(conn: Any) -> None:
    """Full idempotent migration pass: additive schema then legacy data-shape
    migrations.

    Retained as the birth/full-init and test-fixture entry point. The boot
    converge path calls :func:`apply_additive_schema` alone — never this — so it
    never runs the destructive drops or data backfills in
    :func:`apply_legacy_data_migrations`.
    """
    apply_additive_schema(conn)
    apply_legacy_data_migrations(conn)
