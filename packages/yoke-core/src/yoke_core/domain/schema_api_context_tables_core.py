"""``core`` topic table entries for the schema cheat sheet.

Sibling of :mod:`schema_api_context_tables` (which combines per-topic
dicts into the canonical ``CANONICAL_TABLES``). Holds the ``core``
topic entries: items, epic_tasks, epic_dispatch_chains,
epic_progress_notes, item_dependencies, events, event_registry,
ouroboros_entries.

Pure data only — no I/O, no DB connections, no imports beyond stdlib.
"""

from __future__ import annotations


CORE_TABLES: dict[str, dict] = {
    "items": {
        "columns": [
            ("id", "INTEGER"),
            ("title", "TEXT"),
            ("type", "TEXT"),
            ("status", "TEXT"),
            ("priority", "TEXT"),
            ("project_id", "INTEGER"),
            ("project_sequence", "INTEGER"),
            ("github_issue", "TEXT"),
            ("worktree", "TEXT"),
            ("frozen", "INTEGER"),
            ("blocked", "INTEGER"),
            ("blocked_reason", "TEXT"),
            ("deployment_flow", "TEXT"),
            ("flow", "TEXT"),
            ("deploy_stage", "TEXT"),
            ("source", "TEXT"),
            ("owner", "TEXT"),
            ("created_at", "TEXT"),
            ("updated_at", "TEXT"),
        ],
        "notes": (
            "Backlog row keyed by global bare-integer id for internal joins. "
            "The primary key is `id`; items has NO `item_id` or `public_id` column. "
            "`item_id` is a foreign-key column on OTHER tables, "
            "so self-orient with `WHERE id = <n>` here. Public item refs are "
            "project-scoped: join `items.project_id` to `projects.id` and "
            "render `{projects.public_item_prefix}-{items.project_sequence}` "
            "inside project context; the old item-level project slug field "
            "has been deleted. The GitHub linkage is the single `github_issue` "
            "column — there is no "
            "`github_issue_number` and no `github_url`. "
            "The lifecycle columns are `type` and `status`; there "
            "is NO `item_type` column and NO `lifecycle_status` column. "
            "There is also NO `kind` column on items — the function-call "
            "envelope's `target.kind` discriminator "
            "(`item|epic_task|qa_requirement|session|process`) is the "
            "dispatcher's row-type tag, not an items column. Use `type` "
            "for the items lifecycle-type column with values `issue` "
            "and `epic`. "
            "Project authority is `project_id` joined to `projects.id`; "
            "`project_sequence` is the per-project public item number. "
            "There is no item-level project slug column. "
            "items.body is a virtual rendered field (use "
            "`items get YOK-N body` or read the structured-field columns "
            "directly): spec, design_spec, technical_plan, worktree_plan, "
            "shepherd_log, shepherd_caveats, test_results, deploy_log, "
            "browser_qa_metadata, db_mutation_profile, "
            "db_compatibility_attestation, architecture_impact, "
            "resolution, resolution_ref, resolution_comment, "
            "spec_updated_at, spec_updated_by, rework_count, merged_at, "
            "deployed_to. The worktree column holds the branch slug; the "
            "absolute worktree path lives on epic_tasks.worktree_path, "
            "not on items."
        ),
    },
    "epic_tasks": {
        "columns": [
            ("id", "INTEGER"),
            ("epic_id", "INTEGER"),
            ("task_num", "INTEGER"),
            ("title", "TEXT"),
            ("status", "TEXT"),
            ("body", "TEXT"),
            ("dependencies", "TEXT"),
            ("worktree", "TEXT"),
            ("last_activity_at", "TEXT"),
        ],
        "notes": (
            "Keyed by (epic_id, task_num). NOT item_id, NOT task_number, "
            "NOT seq, NOT depends_on, NOT description. last_activity_at "
            "is first-class task freshness — stamped by every epic-task "
            "mutation surface (status transitions, body/field updates, "
            "progress notes, epic-task claim acquire/release); "
            "chain_head_freshness reads it for /yoke conduct re-entry. "
            "Task recency previously lived only in task-scoped event rows "
            "— read this column, never the events ledger (telemetry-only); "
            "NULL means no mutation recorded."
        ),
    },
    "epic_dispatch_chains": {
        "columns": [
            ("id", "INTEGER"),
            ("epic_id", "INTEGER"),
            ("worktree", "TEXT"),
            ("worktree_path", "TEXT"),
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
            "One row per epic-task fan-out worktree. Unique on "
            "(epic_id, worktree). queue is a JSON array of task_nums; "
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
            ("dependent_item", "TEXT"),
            ("blocking_item", "TEXT"),
            ("gate_point", "TEXT"),
            ("satisfaction", "TEXT"),
            ("source", "TEXT"),
            ("session_id", "INTEGER"),
            ("rationale", "TEXT"),
            ("evidence_json", "TEXT"),
            ("created_at", "TEXT"),
        ],
        "notes": (
            "Directional edges between items. dependent_item waits on "
            "blocking_item per gate_point ('activation', 'integration', "
            "'closure', or 'coordination_only' — the last attests "
            "compatible same-file edits with no lifecycle gate). "
            "dependent_item/blocking_item store public YOK-N text refs, "
            "not numeric items.id values. The gate categorization is "
            "`gate_point`; there is NO "
            "`classification` column on this table. satisfaction is "
            "one of 'status:done', 'status:implemented', 'fact:merged'. "
            "source enum: conduct, feed, idea, migration, operator, "
            "refine, shepherd. Reader: `yoke shepherd "
            "dependency-list YOK-N` (returns both directions); "
            "registered shepherd dependency mutation wrappers for writes."
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
            ("user_id", "TEXT"),
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
            ("parent_id", "TEXT"),
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
            "`item_activity_days`; strategize/drift anchors read "
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
            "numeric `project_id` joined to projects. "
            "`$.context.detail.actor_role` is present on subagent-delegated "
            "tool-call events and absent on parent-turn calls. "
            "Working forensic SELECT examples (all runnable via "
            "`yoke db read \"...\"`): "
            "filter by (item_id, event_name) — "
            "`SELECT event_name, event_outcome, created_at FROM events "
            "WHERE item_id = <id> AND event_name = 'WorkClaimed' ORDER "
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
            "id. THE surface for 'when did YOK-N reach status X' "
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
    "ouroboros_entries": {
        "columns": [
            ("id", "INTEGER"),
            ("timestamp", "TEXT"),
            ("agent", "TEXT"),
            ("context", "TEXT"),
            ("category", "TEXT"),
            ("body", "TEXT"),
            ("reviewed_at", "TEXT"),
            ("archived_at", "TEXT"),
            ("created_at", "TEXT"),
            ("project_id", "INTEGER"),
        ],
        "notes": (
            "Learning-log / field-note rows. The kind-like discriminator "
            "is `category` and the evidence/content text is `body`; "
            "there are NO `kind` or `evidence` columns on this table. "
            "Project authority is numeric `project_id`; join projects for "
            "the human slug. "
            "Use `created_at` for canonical ordering; `timestamp` is "
            "legacy compatibility."
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
            "controls render order (Progress Log uses 200). Read/write "
            "via `yoke items section get`, `yoke items section "
            "upsert`, and `yoke items section delete`, or the "
            "`items.progress_log.append` function-call which "
            "preserves prior content. There is NO `heading` column."
        ),
    },
}
