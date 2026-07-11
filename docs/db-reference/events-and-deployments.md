# DB Reference — Events, Severity Config, Deployment Runs

Schemas for the unified events log, write-side severity config and registry, deployment runs, run/item membership, run-level QA, and ephemeral / preview environment tracking. Cross-link back from [db-reference.md](../db-reference.md) for entry points, the domain catalog, timestamp discipline, JSON-payload conventions, qa CLI, body write path, and the status lifecycle reference.

## Table: events

Cross-stack structured event log. Unified envelope for agent tool calls, session lifecycle, backend telemetry, frontend analytics, and system events. All source types share the same schema, enabling cross-source queries on a single table.

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
project_id INTEGER NOT NULL DEFAULT 1 -- project context; references projects(id)
item_id TEXT -- backlog item (e.g., 'YOK-N')
task_num INTEGER -- epic task number
agent TEXT -- agent role (e.g., 'engineer', 'tester')
tool_name TEXT -- tool that was called (e.g., 'Bash', 'Read')
duration_ms INTEGER -- execution duration in milliseconds
exit_code INTEGER -- process exit code
trace_id TEXT -- distributed trace ID
parent_id TEXT -- parent event_id for causal chains
anomaly_flags TEXT -- → JSONB on Postgres (array shape); today a comma-separated anomaly-flag list per `docs/event-contract.md` (e.g., 'nonzero_exit,retry_loop')
tool_use_id TEXT -- target first-class dedup key for tool-call events; current live coverage is still incomplete
envelope TEXT -- → JSONB on Postgres; full JSON envelope for lossless storage
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
```

**Indexes:** `source_type`, `session_id`, `event_name`, `created_at`, `actor_id`, `trace_id`, `project_id`, `tool_name`, `(event_kind, event_type)`, plus the partial dedup index `(tool_use_id, event_name) WHERE tool_use_id IS NOT NULL` on DBs with the full correlation surface.

Engine identity is actor-only. Historical JSON envelopes may retain a null
human-user key, but fresh schemas, writers, readers, and filters do not expose
that retired surface.

**Deduplication:** The `event_id` column has a UNIQUE constraint. Inserts use `ON CONFLICT DO NOTHING` so duplicate event IDs are silently dropped.

**Write-side severity filtering:** Before inserting, events are checked against the `severity_config` table. Events below the configured minimum severity for their `(event_name, source_type)` pair are silently dropped without error.

**Retention (prune):** DEBUG=1d, INFO=30d, WARN=90d, ERROR/FATAL=forever. Run `python3 -m yoke_core.cli.db_router events prune` periodically. DEBUG is the on-demand-capture tier (dropped at the default INFO write floor; enable by lowering `severity_config` to DEBUG), so it carries the shortest retention.

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
added_in TEXT -- YOK-N or version when added
status TEXT NOT NULL DEFAULT 'active' -- 'active' | 'deprecated'
```

**Idempotent writes:** `registry add` uses `ON CONFLICT DO NOTHING` semantics — duplicate `event_name` inserts silently succeed (exit 0, no row change). This makes `python3 -m yoke_core.domain.populate_registry` safe to re-run.

**Lifecycle:** Events start as `active`. Use `registry deprecate <name>` to mark events no longer emitted. The `registry audit` subcommand reports stale active entries (registered but not emitted in 30 days) and rogue events (emitted but not registered).

## Table: deployment_runs

One row per pipeline execution. Stage authority lives on the run, not on individual items. A run may be item-bound through `deployment_run_items`, or item-less for environment-level deploys such as Yoke prod/stage redeploys.

```sql
id TEXT PRIMARY KEY -- human-readable slug (e.g., 'run-20260315-001')
project_id INTEGER NOT NULL REFERENCES projects(id)
flow TEXT NOT NULL REFERENCES deployment_flows(id)
target_env TEXT -- 'production', 'staging', 'shmaging', etc.
release_lineage TEXT -- links preview->prod runs (shared lineage ID)
status TEXT NOT NULL DEFAULT 'created' -- created|executing|succeeded|failed|cancelled
current_stage TEXT -- stage authority lives here, not on items
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
started_at TEXT -- when execution actually began
completed_at TEXT
created_by TEXT -- 'operator' or 'system'
```

## Table: deployment_run_items

Membership table linking items to deployment runs. Zero rows for a run are valid when the run is an environment-level deploy with no attached backlog item; do not infer failure from item-less membership after the run has started executing.

```sql
run_id TEXT NOT NULL REFERENCES deployment_runs(id)
item_id INTEGER NOT NULL -- backlog item numeric ID
added_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
PRIMARY KEY (run_id, item_id)
```

**Item-bound vs environment-level execution:**

- Item-bound delivery starts from `/yoke usher YOK-N` or `runs start-for-item`, which creates the run and inserts membership rows.
- Environment-level deploys create the run directly under the project that owns the deployment environment and flow, leave `deployment_run_items` empty, then execute the run id with the Yoke product checkout that supplies the deploy code, build context, and release SHA:

```bash
target_env=<target-env>
target_branch=<main-or-stage>
source_checkout=<source-checkout>
deploy_owner_project=<deploy-owner-project>
git -C "$source_checkout" fetch origin "$target_branch"
git -C "$source_checkout" checkout --detach FETCH_HEAD
YOKE_ENV=<control-plane-env>-db-admin python3 -m yoke_core.cli.db_router runs create-run "$deploy_owner_project" "yoke-${target_env}-release" --target-env "$target_env" --created-by operator
YOKE_ENV=<control-plane-env>-db-admin YOKE_GITHUB_ACTIONS_RELAY_ENV=<hosted-control-plane-env> python3 -m yoke_core.tools.watch_deploy --product-src "$source_checkout" -- {run-id}
```

The deploy-owner project may differ from the product project after environment/flow re-parenting. Every retry or `--from-stage` resume of the item-less run must repeat the same `--product-src` argument. The watcher validates that checkout and derives the registry's canonical 12-character image tag from its exact `HEAD`; a legacy explicit `--image-tag` is accepted only when it resolves to that same commit and is canonicalized before dispatch.

Normal deploys must select the hosted relay explicitly. The only local-App
exception is an attended first deploy that introduces or repairs the relay,
using `YOKE_GITHUB_ACTIONS_LOCAL_AUTHORITY=1` instead of the relay selector.

## Table: deployment_run_qa

Run-level QA requirements materialized at run creation.

```sql
run_id TEXT NOT NULL REFERENCES deployment_runs(id)
check_name TEXT NOT NULL -- e.g., 'smoke-test', 'manual-acceptance'
source TEXT NOT NULL -- 'flow-default', 'item-rollup', 'operator'
blocking INTEGER NOT NULL DEFAULT 1 -- 1 = blocks done transition
status TEXT NOT NULL DEFAULT 'pending' -- pending|passed|failed|waived
updated_at TEXT
PRIMARY KEY (run_id, check_name)
```

## Table: deployment_preview_environments

Preview environment occupancy tracking for deployment runs.

```sql
id INTEGER PRIMARY KEY
project TEXT NOT NULL REFERENCES projects(id)
env_name TEXT NOT NULL -- e.g., 'staging', 'shmaging'
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
branch TEXT NOT NULL -- MUST use 'YOK-{id}' format (see Branch Naming Contract below)
item TEXT -- backlog item (e.g., 'YOK-N')
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

The `branch` column MUST use the value `YOK-{id}` (matching the item's worktree branch name, e.g., `YOK-N`). This convention is required for conduct compatibility -- the conduct skill queries ephemeral environments by `branch='YOK-{id}'` at steps d2, E1, and E3 in `dispatch-context.md`. CI systems that write ephemeral environment records (e.g., `buzz-ephemeral.yml`) must use the same `YOK-{id}` branch value. If a future project uses a different branch naming scheme, both the CI workflow and the conduct skill query must be updated in lockstep.
