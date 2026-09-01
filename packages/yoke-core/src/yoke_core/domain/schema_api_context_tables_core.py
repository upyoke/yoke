"""Core topic table entries for the canonical schema cheat sheet.
Pure data only — no I/O or DB connections."""

from __future__ import annotations

from yoke_core.domain.schema_api_context_tables_items import ITEMS_TABLE
from yoke_core.domain.schema_api_context_tables_ouroboros import OUROBOROS_TABLES
from yoke_core.domain.schema_api_context_tables_worktrees import ITEM_WORKTREE_TABLES

CORE_TABLES: dict[str, dict] = {
    **ITEMS_TABLE,
    **ITEM_WORKTREE_TABLES,
    **OUROBOROS_TABLES,
    "epic_tasks": {
        "columns": [
            ("id", "INTEGER"),
            ("epic_id", "INTEGER"),
            ("task_num", "INTEGER"),
            ("title", "TEXT"),
            ("status", "TEXT"),
            ("body", "TEXT"),
            ("dependencies", "TEXT"),
            ("item_worktree_id", "INTEGER"),
            ("last_activity_at", "TEXT"),
        ],
        "notes": (
            "Keyed by (epic_id, task_num). NOT item_id, NOT task_number, "
            "NOT seq, NOT depends_on, NOT description. last_activity_at "
            "is first-class task freshness — stamped by every epic-task "
            "mutation surface (status transitions, body/field updates, "
            "progress notes, epic-task claim acquire/release); "
            "chain_head_freshness reads it for /yoke conduct re-entry. "
            "dependencies is comma-separated TEXT containing prerequisite "
            "task_num values from the same epic, not JSON. "
            "item_worktree_id references the authoritative lane in "
            "item_worktrees. "
            "Task recency previously lived only in task-scoped event rows "
            "— read this column, never the events ledger (telemetry-only); "
            "NULL means no mutation recorded."
        ),
    },
    "epic_dispatch_chains": {
        "columns": [
            ("id", "INTEGER"),
            ("epic_id", "INTEGER"),
            ("item_worktree_id", "INTEGER"),
            ("queue", "TEXT"),
            ("current_index", "INTEGER"),
            ("current_task", "TEXT"),
            ("current_attempt", "INTEGER"),
            ("max_attempts", "INTEGER"),
            ("no_chain", "INTEGER"),
            ("started_at", "TEXT"),
            ("last_updated", "TEXT"),
        ],
        "notes": (
            "One row per epic-task fan-out lane. Unique on "
            "(epic_id, item_worktree_id). queue is a JSON array of task_nums; "
            "current_task is the head task being worked. Conduct's "
            "task activation refreshes current_task / current_attempt / "
            "last_updated when it sets epic_tasks.status='implementing' "
            "so telemetry and scheduler views see the live dispatch."
        ),
    },
    "epic_progress_notes": {
        "columns": [
            ("id", "INTEGER"),
            ("epic_id", "INTEGER"),
            ("task_num", "INTEGER"),
            ("note_num", "INTEGER"),
            ("body", "TEXT"),
            ("created_at", "TEXT"),
        ],
        "notes": "Append-only. NOT note (the content column is body).",
    },
    "item_dependencies": {
        "columns": [
            ("id", "INTEGER"),
            ("dependent_item_id", "INTEGER"),
            ("blocking_item_id", "INTEGER"),
            ("gate_point", "TEXT"),
            ("satisfaction", "TEXT"),
            ("source", "TEXT"),
            ("session_id", "INTEGER"),
            ("rationale", "TEXT"),
            ("evidence_json", "TEXT"),
            ("created_at", "TEXT"),
        ],
        "notes": (
            "Directional edges between items. The dependent waits on "
            "the blocker per gate_point ('activation', 'integration', "
            "'closure', or 'coordination_only' — the last attests "
            "compatible same-file edits with no lifecycle gate). "
            "dependent_item_id/blocking_item_id are integer FKs to "
            "items.id. API/list still project PREFIX-N. The gate "
            "categorization is `gate_point`; there is NO "
            "`classification` column on this table. satisfaction is "
            "one of 'status:done', 'status:implemented', 'fact:merged'. "
            "source enum: conduct, feed, idea, migration, operator, "
            "refine, shepherd. Reader `items.dependency.list` "
            "projects `direction`/`other_item` (wrong guess: result keys "
            "`dependent_item`/`blocking_item` — storage is *_item_id)."
        ),
    },
    "events": {
        "columns": [
            ("id", "INTEGER"),
            ("event_id", "TEXT"),
            ("source_type", "TEXT"),
            ("session_id", "TEXT"),
            ("severity", "TEXT"),
            ("event_kind", "TEXT"),
            ("event_type", "TEXT"),
            ("event_name", "TEXT"),
            ("event_outcome", "TEXT"),
            ("org_id", "TEXT"),
            ("actor_id", "INTEGER"),
            ("environment", "TEXT"),
            ("service", "TEXT"),
            ("project_id", "INTEGER"),
            ("item_id", "TEXT"),
            ("task_num", "INTEGER"),
            ("agent", "TEXT"),
            ("tool_name", "TEXT"),
            ("duration_ms", "INTEGER"),
            ("exit_code", "INTEGER"),
            ("trace_id", "TEXT"),
            ("anomaly_flags", "TEXT"),
            ("tool_use_id", "TEXT"),
            ("turn_id", "TEXT"),
            ("hook_event_name", "TEXT"),
            ("envelope", "TEXT"),
            ("created_at", "TEXT"),
        ],
        "notes": (
            "Append-only TELEMETRY ledger — diagnosis/audit only, never "
            "application state. Status/transition questions read "
            "`item_status_transitions`; board activity reads "
            "`item_activity_days`; board/Overview code meters read "
            "`project_code_days`; strategize/drift anchors read "
            "`strategy_checkpoints`; session/tool-call liveness reads "
            "`harness_sessions` columns + `session_tool_calls`; "
            "dispatcher idempotency reads `function_call_ledger`; "
            "path-claim override gating reads `path_claim_overrides`; "
            "the DB-claim reviewed-negative attestation reads "
            "`items.db_mutation_profile` (reviewed_negative key). "
            "The event-specific payload lives "
            "under `$.context.*` inside `envelope` (top-level envelope "
            "keys are metadata like `$.event_id` / `$.event_name`); the "
            "structured outcome string lives in `event_outcome`; the "
            "timestamp lives in `created_at`; project authority is "
            "numeric `project_id` joined to projects. `item_id` is TEXT "
            "(bare-numeric text — quote in SQL as `'<id>'`, never INTEGER). "
            "`$.context.detail.actor_role` is present on subagent-delegated "
            "tool-call events and absent on parent-turn calls. "
            "Working forensic SELECT examples (all runnable via "
            '`yoke db read "..."`): '
            "filter by (item_id, event_name) — "
            "`SELECT event_name, event_outcome, created_at FROM events "
            "WHERE item_id = '<id>' AND event_name = 'WorkClaimed' ORDER "
            "BY created_at DESC`; recent events by "
            "session_id — `SELECT event_name, event_outcome, created_at "
            "FROM events WHERE session_id = '<session-id>' ORDER BY "
            "created_at DESC LIMIT 25`."
        ),
    },
    "item_status_transitions": {
        "columns": [
            ("id", "INTEGER"),
            ("item_id", "INTEGER"),
            ("task_num", "INTEGER"),
            ("from_status", "TEXT"),
            ("to_status", "TEXT"),
            ("source", "TEXT"),
            ("session_id", "TEXT"),
            ("actor_id", "INTEGER"),
            ("project_id", "INTEGER"),
            ("created_at", "TEXT"),
        ],
        "notes": (
            "Item/task status transition HISTORY (state, not telemetry) — "
            "written at mutation time by every status writer. "
            "`task_num IS NULL` = item-level transition; non-null = "
            "epic-task transition with item_id = the parent epic's item "
            "id. THE surface for 'when did PREFIX-N reach status X' "
            "questions (the retired pattern was scanning "
            "ItemStatusChanged/TaskStatusChanged envelopes in events): "
            "`SELECT from_status, to_status, source, created_at FROM "
            "item_status_transitions WHERE item_id = <id> ORDER BY id "
            "DESC LIMIT 10`. Python writer/reader: "
            "yoke_core.domain.item_status_transitions "
            "(record_item_transition / record_task_transition / "
            "latest_transition)."
        ),
    },
    "item_activity_days": {
        "columns": [
            ("id", "INTEGER"),
            ("project_id", "INTEGER"),
            ("item_id", "INTEGER"),
            ("day", "TEXT"),
        ],
        "notes": (
            "Board activity rollup: one row per (project, item, UTC day) "
            "an item was touched by a real domain mutation (transitions, "
            "claim acquire/release, structured/section writes, epic-task "
            "mutations, qa writes — yoke_core.domain.item_activity). "
            "UNIQUE(project_id, item_id, day); surrogate `id` is the "
            "board cache's monotonic invalidation watermark. NOT an "
            "events-derived view — the one-time historical backfill came "
            "from the legacy ledger scan, go-forward rows come only from "
            "mutation-site touches (decision record "
            "board-activity-semantics)."
        ),
    },
    "project_code_days": {
        "columns": [
            ("id", "INTEGER"),
            ("project_id", "INTEGER"),
            ("day", "TEXT"),
            ("commit_count", "INTEGER"),
            ("lines_changed", "INTEGER"),
        ],
        "notes": (
            "Daily commit/line rollup for board + Overview code meters "
            "(yoke_core.domain.project_code_days). UNIQUE(project_id, day). "
            "Ingest from the machine commit-cache via board.data.get "
            "`code_days` payload (or domain upsert_days). Local "
            ".commit-cache.json is ingest scratch only — not Overview "
            "authority. Do not invent a parallel git-event code series."
        ),
    },
    "strategy_checkpoints": {
        "columns": [
            ("id", "INTEGER"),
            ("project_id", "INTEGER"),
            ("kind", "TEXT"),
            ("created_at", "TEXT"),
        ],
        "notes": (
            "Strategize / drift-review completion anchors per project; "
            "kind IN ('strategize','drift_review'). MAX(created_at) per "
            "project bounds the strategize delta window and the "
            "drift-review delivered-delta. CLI: `yoke strategy checkpoint "
            "record --project P --kind strategize` / `yoke strategy "
            "checkpoint latest --project P`."
        ),
    },
    "event_registry": {
        "columns": [
            ("event_name", "TEXT"),
            ("event_kind", "TEXT"),
            ("event_type", "TEXT"),
            ("owner_service", "TEXT"),
            ("description", "TEXT"),
            ("context_schema", "TEXT"),
            ("severity_default", "TEXT"),
            ("added_in", "TEXT"),
            ("status", "TEXT"),
        ],
        "notes": (
            "Event catalog keyed by `event_name`. There is NO `name` "
            "column on this table; use event_name for joins and lookups."
        ),
    },
    "item_sections": {
        "columns": [
            ("item_id", "INTEGER"),
            ("section_name", "TEXT"),
            ("content", "TEXT"),
            ("ordering", "INTEGER"),
            ("created_at", "TEXT"),
            ("updated_at", "TEXT"),
            ("source", "TEXT"),
        ],
        "notes": (
            "Per-item section rows that render into items.body alongside "
            "the structured fields. Composite key (item_id, "
            "section_name); section_name is case-sensitive. ordering "
            "controls render order (Progress Log uses 200; NULL still "
            "renders). Read/write via `yoke items section get` / "
            "`upsert` / `delete`, or the "
            "`items.progress_log.append` function-call which "
            "preserves prior content. There is NO `heading` column."
        ),
    },
}
