# DB Reference — Events and Environment Tracking

Schemas for the unified events log, write-side severity config and registry, and ephemeral / preview environment tracking. Cross-link back from [db-reference.md](../db-reference.md) for entry points, the domain catalog, timestamp discipline, JSON-payload conventions, qa CLI, body write path, and the status lifecycle reference.

## Table: events

Cross-stack structured event log. Unified envelope for agent tool calls, session lifecycle, backend telemetry, frontend analytics, and system events. All source types share the same schema, enabling cross-source queries on a single table. Workbench analytics use the anonymous `/api/events` collector; [workbench telemetry](../../events-doctor-ouroboros.md) explains consent, admission, URL hygiene, packaging, and durable `actors.attribution` ownership.

Compatibility note: first-class tool-call correlation columns are optional across local installs and emitters. Readers and emitters must tolerate their absence until all live event tables expose the full correlation surface.

```sql
id INTEGER PRIMARY KEY
event_id TEXT UNIQUE NOT NULL -- UUID, deduplication key (ON CONFLICT DO NOTHING)
source_type TEXT NOT NULL -- 'agent' | 'backend' | 'frontend' | 'system' | 'script' | 'hook' | 'skill'
session_id TEXT NOT NULL -- session/request correlation ID
severity TEXT NOT NULL DEFAULT 'INFO' -- DEBUG | INFO | WARN | ERROR | FATAL
event_kind TEXT NOT NULL -- taxonomy tier 1 (e.g., 'system', 'domain', 'user')
event_type TEXT NOT NULL -- taxonomy tier 2 (e.g., 'tool_call', 'session')
event_name TEXT NOT NULL -- PascalCase event name (e.g., 'HarnessToolCallCompleted')
event_outcome TEXT -- nullable outcome (e.g., 'completed', 'failed')
org_id TEXT -- organization identifier
actor_id INTEGER -- nullable Yoke control-plane subject; references actors(id)
environment TEXT -- runtime environment (e.g., 'dev', 'prod')
service TEXT NOT NULL DEFAULT 'cli' -- emitting service
project_id INTEGER -- nullable project context; references projects(id); no implicit attribution
item_id TEXT -- owned backlog join key; public reads project it to public_ref
task_num INTEGER -- epic task number
agent TEXT -- agent role (e.g., 'engineer', 'tester')
tool_name TEXT -- tool that was called (e.g., 'Bash', 'Read')
duration_ms INTEGER -- execution duration in milliseconds
exit_code INTEGER -- process exit code
trace_id TEXT -- distributed trace ID
anomaly_flags TEXT -- → JSONB on Postgres (array shape); today a comma-separated anomaly-flag list per `docs/event-contract.md` (e.g., 'nonzero_exit,retry_loop')
tool_use_id TEXT -- target first-class dedup key for tool-call events; current live coverage is still incomplete
client_timing_id TEXT -- key a hook client minted for its own dispatch, so the wall time it reports afterwards finds this row by index; cleared once that report lands
envelope TEXT -- → JSONB on Postgres; full JSON envelope for lossless storage
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
```

**Indexes:** `source_type`, `session_id`, `event_name`, `created_at`, `actor_id`, `trace_id`, `project_id`, `tool_name`, `(event_kind, event_type)`, plus the partial dedup index `(tool_use_id, event_name) WHERE tool_use_id IS NOT NULL` and the partial correlation index `(client_timing_id) WHERE client_timing_id IS NOT NULL` on DBs with the full correlation surface. Correlate through an indexed column; matching a substring of `envelope` with LIKE has no index to use and reads every row the other predicates admit.

Event reads project nested envelope item identities and item history `target_id` to complete public refs; storage keeps owned join keys. Other record IDs retain their domain meaning.

Engine identity is actor-only. Historical JSON envelopes may retain a null human-user key, but fresh schemas, writers, readers, and filters do not expose that retired surface.

**Deduplication:** The `event_id` column has a UNIQUE constraint. Inserts use `ON CONFLICT DO NOTHING` so duplicate event IDs are silently dropped.

**Write-side severity filtering:** Before inserting, events are checked against the `severity_config` table. Events below the configured minimum severity for their `(event_name, source_type)` pair are silently dropped without error. The acknowledged anonymous frontend collector bypasses this optional filter; retention still applies.

**Retention (prune):** DEBUG=1d, INFO=30d, WARN=90d, STATUS/ERROR/FATAL=forever. Event preview and delete are LIMIT-batched (`--batch-size`, default 1000). LIMIT caps matching rows, not scanned rows or query duration; the monotonic `--max-seconds` deadline (default 30) is checked between statements, and each event count/delete/leftover probe sets `statement_timeout` to the remaining budget so a sparse scan, `ORDER BY`, or leftover peek cannot outlive the pass. That timeout is event-only: after each event probe it is restored to the incoming `SHOW statement_timeout` (not forced to zero) before ledger, dispatch-intent, and `session_tool_calls` helpers, which keep their existing retention contracts. Optionally batch-capped (`--max-batches`); counts are exact or labeled `>=N (partial)`. A statement timeout is a graceful stop: already-committed batches stay. Referenced `event_id` rows (path-audit tables) are kept on every event delete path. Obsolete-name cleanup is opt-in (`--purge-obsolete`). Live invocation: `python3 -m yoke_core.cli.db_router events prune [--dry-run]`. Rerun after `stopped: batch/time budget`. No automatic prune timer lives in this repo; do not invent a parallel scheduler. DEBUG is the on-demand-capture tier (dropped at the default INFO write floor; enable by lowering `severity_config` to DEBUG), so it carries the shortest retention.

## Table: severity_config

Write-side severity filtering configuration for the events table. Controls which severity levels are persisted per event name and source type combination.

```sql
id INTEGER PRIMARY KEY
event_name TEXT NOT NULL DEFAULT '*' -- event name pattern ('*' = wildcard)
source_type TEXT NOT NULL DEFAULT '*' -- source type pattern ('*' = wildcard)
min_severity TEXT NOT NULL DEFAULT 'INFO' -- DEBUG | INFO | WARN | ERROR | FATAL
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
UNIQUE(event_name, source_type)
```

**Lookup order:** exact `(event_name, source_type)` > `(event_name, *)` > `(*, source_type)` > `(*, *)`. First match wins. Seeded with catch-all `(*, *, INFO)` on init.

## Table: event_registry

Central registry of all known event types. Governs event naming, ownership, and lifecycle. Used by `yoke_core.domain.observe` (lint-event-registry guardrail) (PreToolUse hook) and doctor health checks to enforce event governance.

```sql
event_name TEXT PRIMARY KEY -- PascalCase event name (e.g., 'HarnessToolCallCompleted')
event_kind TEXT NOT NULL -- taxonomy tier 1 (e.g., 'system', 'domain')
event_type TEXT NOT NULL -- taxonomy tier 2 (e.g., 'tool_call', 'session')
owner_service TEXT NOT NULL -- emitting service (e.g., 'yoke_core.domain.observe')
description TEXT NOT NULL -- human-readable description
context_schema TEXT -- optional JSON schema for context payload
severity_default TEXT NOT NULL DEFAULT 'INFO' -- default severity level
added_in TEXT -- PREFIX-N or version when added
status TEXT NOT NULL DEFAULT 'active' -- 'active' | 'deprecated'
```

**Idempotent writes:** `registry add` uses `ON CONFLICT DO NOTHING` semantics — duplicate `event_name` inserts silently succeed (exit 0, no row change). This makes `python3 -m yoke_core.domain.populate_registry` safe to re-run.

**Lifecycle:** Events start as `active`. Use `registry deprecate <name>` to mark events no longer emitted. The `registry audit` subcommand reports stale active entries (registered but not emitted in 30 days) and rogue events (emitted but not registered).

## Deployment run authority

[Deployment run records](deployment-run-records.md) defines run lineage, composition and custody, stage receipts, membership and settlement, the deploy lock, idempotent creation, and blocking QA. Read it before creating or executing a run or interpreting release completion.

## Table: deployment_preview_environments

Preview environment occupancy tracking for deployment runs.

```sql
id INTEGER PRIMARY KEY
project TEXT NOT NULL REFERENCES projects(id)
env_name TEXT NOT NULL -- e.g., 'stage', 'sandbox'
run_id TEXT REFERENCES deployment_runs(id)
status TEXT NOT NULL DEFAULT 'available' -- available | claimed | stale
url TEXT
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
env_type TEXT NOT NULL DEFAULT 'adhoc' -- shared | adhoc
UNIQUE(project, env_name)
```

## Table: ephemeral_environments

Tracks per-branch ephemeral environments for pre-merge E2E validation. GitHub Actions creates environments; Yoke tracks lifecycle via `python3 -m yoke_core.cli.db_router envs`.

```sql
id INTEGER PRIMARY KEY
project TEXT NOT NULL REFERENCES projects(id)
branch TEXT NOT NULL -- MUST use 'PREFIX-{id}' format (see Branch Naming Contract below)
item TEXT -- backlog item (e.g., 'PREFIX-N')
workflow_run_id TEXT -- GitHub Actions run ID that created this environment
github_ref TEXT -- git ref used for the environment
port_api INTEGER
port_web INTEGER
url TEXT
status TEXT NOT NULL DEFAULT 'pending' -- pending | starting | running | healthy | stopped | failed
started_at TEXT
stopped_at TEXT
health_check_url TEXT
deployed_sha TEXT -- commit SHA of last pushed code (enables push/poll short-circuit)
created_at TEXT
UNIQUE(project, branch)
```

### Branch Naming Contract

The `branch` column MUST use the value `PREFIX-{id}` (matching the item's worktree branch name, e.g., `PREFIX-N`). This convention is required for conduct compatibility -- the conduct skill queries ephemeral environments by `branch='PREFIX-{id}'` at steps d2, E1, and E3 in `dispatch-context.md`. CI systems that write ephemeral environment records (e.g., `external-webapp-ephemeral.yml`) must use the same `PREFIX-{id}` branch value. If a future project uses a different branch naming scheme, both the CI workflow and the conduct skill query must be updated in lockstep.
