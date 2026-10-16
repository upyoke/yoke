"""Additive schema convergence and initial schema invariants."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.epic_task_membership import MEMBERSHIP_FINALIZED_COLUMN
from yoke_core.domain.schema_checks import (
    _validate_epic_task_statuses,
    _validate_item_workflow_stages,
)
from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _table_exists,
)
from yoke_core.domain.schema_harness_session_columns import (
    apply_harness_session_columns,  # noqa: F401
)
from yoke_core.domain.schema_migrations import _ensure_qa_runs_verdict_trigger
from yoke_core.domain.projects_github_sync_mode_schema import (
    github_sync_mode_column_sql,
)


def apply_work_claim_scope_column(conn: Any) -> None:
    """Converge scope before any work-claim index can reference it."""
    if not _table_exists(conn, "work_claims"):
        return
    _add_column_if_not_exists(conn, "work_claims", "scope", "TEXT DEFAULT NULL")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_work_claims_scope ON work_claims(scope)"
    )
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
    belongs in permanent ordered migration history, not here. A column added to
    a table the release driver reads must land with window-tolerant reads in the
    same change: ``runs get`` / ``runs list`` and their shared projection
    substitute empty for a declared column the live table has not yet converged.
    """
    # Scope-bound replay metadata. Empty defaults make legacy rows explicitly
    # unverifiable; the dispatcher denies them instead of replaying across a
    # newly-authenticated actor or authorization scope.
    for column in ("actor_id", "authorization_scope", "payload_checksum"):
        _add_column_if_not_exists(
            conn, "function_call_ledger", column, "TEXT NOT NULL DEFAULT ''"
        )
    conn.commit()

    _add_column_if_not_exists(conn, "projects", "retired_at", "TIMESTAMPTZ")
    _add_column_if_not_exists(conn, "actors", "name", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_not_exists(
        conn, "actors", "status", "TEXT NOT NULL DEFAULT 'active'"
    )
    conn.commit()

    # Idempotent ADD COLUMN migrations for epic_tasks
    _add_column_if_not_exists(conn, "epic_tasks", "body", "TEXT")
    _add_column_if_not_exists(conn, "epic_tasks", "github_issue", "TEXT")
    _add_column_if_not_exists(
        conn, "epic_tasks", "item_worktree_id", "INTEGER DEFAULT NULL"
    )
    _add_column_if_not_exists(conn, "epic_tasks", "max_attempts", "INTEGER DEFAULT 5")
    _add_column_if_not_exists(conn, "epic_tasks", "agent_id", "TEXT")
    _add_column_if_not_exists(conn, "epic_tasks", "last_heartbeat", "TIMESTAMPTZ")
    # task-freshness state: stamped by every epic-task mutation surface.
    _add_column_if_not_exists(conn, "epic_tasks", "last_activity_at", "TIMESTAMPTZ")
    _add_column_if_not_exists(
        conn, "epic_dispatch_chains", "item_worktree_id", "INTEGER DEFAULT NULL"
    )
    conn.commit()

    # Merge-lock scope. A merge serializes against other merges landing on the
    # same branch of the same project; a merge into another project, or into a
    # different target branch, contends for nothing. NULL on a legacy row means
    # "scope unknown", which blocks conservatively.
    _add_column_if_not_exists(conn, "merge_locks", "project_slug", "TEXT DEFAULT NULL")
    _add_column_if_not_exists(conn, "merge_locks", "target_branch", "TEXT DEFAULT NULL")
    conn.commit()

    # Per-project GitHub sync switch defaults safely when added to a
    # previously born universe.
    _add_column_if_not_exists(
        conn, "projects", "github_sync_mode", github_sync_mode_column_sql()
    )
    # Project-wide governed-migration compatibility posture. Nullable keeps
    # the founder-cutover fallback for projects created before the policy was
    # explicit while preserving stored policy during universe portability.
    _add_column_if_not_exists(conn, "projects", "breakage_policy", "TEXT DEFAULT NULL")
    conn.commit()

    # Canonical work-claim scope. Nullable on additive convergence because
    # migration 0020 backfills every legacy target before enforcing the hard
    # cutover; fresh tables declare the final NOT NULL shape directly.
    apply_work_claim_scope_column(conn)

    # claim-reason / release-intent state (the events ledger is
    # telemetry-only; acquire/release paths stamp these columns).
    _add_column_if_not_exists(conn, "work_claims", "reason", "TEXT DEFAULT NULL")
    _add_column_if_not_exists(conn, "work_claims", "reason_intent", "TEXT DEFAULT NULL")
    _add_column_if_not_exists(
        conn, "work_claims", "release_reason_intent", "TEXT DEFAULT NULL"
    )
    conn.commit()

    # items.source stores the stringified actors.id for the item originator;
    # every writer names it, and '' marks a row with no recorded source.
    _add_column_if_not_exists(conn, "items", "source", "TEXT NOT NULL DEFAULT ''")
    conn.commit()

    # Numeric project authority must be explicitly attributed. Adding this
    # column to populated unattributed data refuses instead of guessing.
    _add_column_if_not_exists(conn, "items", "project_id", "INTEGER NOT NULL")
    conn.commit()

    # Add deployment_flow and deploy_stage columns
    _add_column_if_not_exists(conn, "items", "deployment_flow", "TEXT")
    _add_column_if_not_exists(conn, "items", "deploy_stage", "TEXT")
    conn.commit()

    # Durable handoff between merge-queue admission and item close-out.
    # Nullable timestamps make the four-state marker self-sufficient on ADD.
    _add_column_if_not_exists(conn, "items", "merge_queue_pr_number", "TEXT")
    _add_column_if_not_exists(conn, "items", "merge_queue_enqueued_at", "TIMESTAMPTZ")
    _add_column_if_not_exists(conn, "items", "merge_queue_landed_at", "TIMESTAMPTZ")
    _add_column_if_not_exists(conn, "items", "merge_queue_notified_at", "TIMESTAMPTZ")
    conn.commit()

    # Add numeric project authority to ouroboros_entries.
    _add_column_if_not_exists(
        conn, "ouroboros_entries", "project_id", "INTEGER DEFAULT NULL"
    )
    conn.commit()

    # Add project column to release_entries
    _add_column_if_not_exists(conn, "release_entries", "project_id", "INTEGER NOT NULL")
    conn.commit()

    # owner — actor FK companion to items.source. Nullable here because
    # the one-shot migration backfills it during the source/owner
    # conversion; new write paths in :mod:`backlog_create_op` resolve
    # both to non-null actor IDs. The column type stays
    # TEXT to preserve historical source/owner values; readers cast to
    # int at the boundary.
    _add_column_if_not_exists(conn, "items", "owner", "TEXT")

    # Durable item-close outcome. These scalar fields remain part of the live
    # items read/write contract and must exist on both fresh and fleet-upgraded
    # universes so portable archives retain cancellation history.
    _add_column_if_not_exists(conn, "items", "resolution", "TEXT")
    _add_column_if_not_exists(conn, "items", "resolution_ref", "TEXT")
    _add_column_if_not_exists(conn, "items", "resolution_comment", "TEXT")

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

    # db_mutation_profile / db_compatibility_attestation — governed
    # DB-mutation contract.  DB-level NOT NULL DEFAULT makes omission
    # structurally impossible: every INSERT lands a row with a valid negative
    # default and existing rows populate at ADD time.  Annotated for Postgres
    # cutover; see :data:`yoke_core.domain.sql_json.JSONB_COLUMNS`.
    _add_column_if_not_exists(
        conn,
        "items",
        "db_mutation_profile",
        'TEXT NOT NULL DEFAULT \'{"state":"none"}\'',  # → JSONB on Postgres
    )
    _add_column_if_not_exists(
        conn,
        "items",
        "db_compatibility_attestation",
        "TEXT NOT NULL DEFAULT '{}'",  # → JSONB on Postgres
    )
    conn.commit()

    # github_body_compact_pending — nullable native instant set when the
    # last successful GitHub body sync landed the compact mirror (body
    # over budget) and cleared when a full-body sync lands. The repair
    # pass (backfill-oversized-bodies) reads it as its candidate queue;
    # owner: yoke_core.domain.backlog_github_body_budget.
    _add_column_if_not_exists(
        conn, "items", "github_body_compact_pending", "TIMESTAMPTZ"
    )
    _add_column_if_not_exists(conn, "items", MEMBERSHIP_FINALIZED_COLUMN, "TIMESTAMPTZ")
    conn.commit()

    # architecture_impact — operator-authored enum classifying the item's
    # relationship to the project architecture model. NOT NULL DEFAULT 'none'
    # populates existing rows at ADD time; refine / idea_readiness_check
    # escalates 'uncertain' rows.
    _add_column_if_not_exists(
        conn, "items", "architecture_impact", "TEXT NOT NULL DEFAULT 'none'"
    )
    conn.commit()

    # Add source column to item_sections
    _add_column_if_not_exists(
        conn, "item_sections", "source", "TEXT NOT NULL DEFAULT 'operator'"
    )
    conn.commit()

    # strategy_docs.archived_at — nullable ISO timestamp marking an archived
    # doc (NULL = active). Self-sufficient on ADD (NULL is the valid active
    # default); flipped by strategy.doc.archive / strategy.doc.unarchive.
    _add_column_if_not_exists(
        conn, "strategy_docs", "archived_at", "TIMESTAMPTZ DEFAULT NULL"
    )
    conn.commit()

    # Existing environments tables predate the delivery stamp leaf.
    if _table_exists(conn, "environments"):
        _add_column_if_not_exists(
            conn, "environments", "last_deployed_at", "TIMESTAMPTZ"
        )
    conn.commit()


def finalize_initial_schema(conn: Any) -> None:
    """Install initial schema indexes and evidence invariants."""
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_items_project_sequence ON items(project_id, project_sequence)"
    )
    _ensure_qa_runs_verdict_trigger(conn)
    conn.commit()
    _validate_item_workflow_stages(conn)
    _validate_epic_task_statuses(conn)


def apply_idempotent_migrations(conn: Any) -> None:
    """Converge additive schema and initialize its invariants."""
    apply_additive_schema(conn)
    finalize_initial_schema(conn)
