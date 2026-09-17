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
item_id TEXT -- backlog item (e.g., 'PREFIX-N')
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

Engine identity is actor-only. Historical JSON envelopes may retain a null
human-user key, but fresh schemas, writers, readers, and filters do not expose
that retired surface.

**Deduplication:** The `event_id` column has a UNIQUE constraint. Inserts use `ON CONFLICT DO NOTHING` so duplicate event IDs are silently dropped.

**Write-side severity filtering:** Before inserting, events are checked against the `severity_config` table. Events below the configured minimum severity for their `(event_name, source_type)` pair are silently dropped without error.

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

## Table: deployment_runs

One row per pipeline execution. Stage authority lives on the run, not on individual items. A run may be item-bound through `deployment_run_items`, or item-less for environment-level deploys such as Yoke prod/stage redeploys.

```sql
id TEXT PRIMARY KEY -- human-readable slug (e.g., 'run-20260315-001')
project_id INTEGER NOT NULL REFERENCES projects(id)
flow TEXT NOT NULL REFERENCES deployment_flows(id)
target_tier TEXT -- persistent | ephemeral | NULL (merge-only)
target_environment_id INTEGER -- internal REFERENCES environments(id); required exactly when target_tier='persistent'
release_lineage TEXT -- links preview->prod runs (shared lineage ID)
status TEXT NOT NULL DEFAULT 'created' -- created|executing|succeeded|failed|cancelled
current_stage TEXT -- stage authority lives here, not on items
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
started_at TEXT -- when execution actually began
completed_at TEXT
created_by TEXT -- 'operator' or 'system'
carried_work TEXT -- → JSONB on Postgres; resolved items and unresolved commit SHAs
artifact_identity TEXT -- optional immutable build artifact identity, distinct from release_lineage
composition_resolution TEXT -- explicit first-baseline attribution resolution
composition_frozen_at TEXT -- immutable admission-freeze timestamp
requirement_snapshot TEXT -- full flow-level QA plan/case content frozen at start
```

A run copies the internal `target_tier` and `target_environment_id` from its flow. Operators select or override a persistent target only with `--environment <registered-name>`; numeric keys are never accepted or emitted by the operator surface. Setting `status=succeeded` stamps `environments.last_deployed_at` on the referenced row.

Successful completion also compares this run's immutable `release_lineage`
with the previous succeeded run for the same project and target environment.
The resulting `carried_work` object keeps item matches under `items` and
unresolved first-parent commits as bare SHAs under `commits`. Recording it
changes no lifecycle state; historical runs remain unset and recording is
forward-only. The record is evidence, not membership — enrolling from it is a
separate step, described under release admission below.

The comparison runs wherever the completion does. A machine holding the
project's registered checkout reads git directly; anywhere else — including a
control plane serving an HTTPS-only project, which holds no checkout of it and
never will — the same comparison runs over the project's own authorized
repository binding. `derivation.source` names which answered (`checkout`,
`repository_provider`, or `none`).

**An empty release and an unanswerable comparison are different facts.**
`derivation.contents_known` is true only when the comparison actually ran, and
`derivation.status` is derived from it: `derived` when commits were attributed,
`empty` when the run genuinely carries nothing, and `unknown` when nobody could
look. `derivation.reason` names the case and `derivation.recovery` names the
repair. Readers must not treat `unknown` as `empty`: an unknown record
suppresses both automatic enrollment and the omitted-delivery-ready-member scan
at composition freeze, because a set nobody computed can neither be admitted
nor cleared. Attribution is repaired, never guessed.

A record is written once and then frozen, which is right for a comparison that
ran and wrong for one that could not. `deployment_runs.carried_work.repair`
(CLI: `yoke deployment-runs carried-work repair RUN-ID`) replaces exactly that
case: it refuses a record that was derived, refuses to write a second
unanswerable derivation, and names the reason the retry still failed.

Completion gates ask whether the deployed candidate **contains** an item's
recorded merge, not whether it equals it — a batch has one tip, so equality
could only ever complete a single-item release. That ancestry read uses the
same comparison source and needs no commit listing, so a history longer than
the reader pages still answers truthfully. An unreadable comparison refuses by
its own name rather than reporting the merge absent.

Definition-schema-v2 runs freeze admission before execution. The candidate
`release_lineage` must be a full commit SHA; every nonterminal delivery-ready
change carried by that candidate must be a member, while done history,
merge-only flows, Task items, and Epic task graphs are not admitted implicitly.
The run records the shared artifact identity, an immutable composition digest,
the effective flow for every member, and full recoverable QA requirement/plan
content. Missing first-baseline attribution must be resolved explicitly before
start. Cancellation preserves the frozen evidence. Schema-v1 runs retain their
legacy start behavior.

**A start completes its own membership.** Item-bound composition (`deployment_runs.start_for_item`, `deployment_runs.validate_composition`) and the driver's `deployment_runs.execution.context` read each enroll every delivery-ready item the pinned candidate carries and the run does not hold, through the same admission validation `add_item` uses, and print the public references added. Enrollment takes the item workflow-binding locks and then the run row, the order `lock_run_with_stable_membership` and `add_item` already use, and locks every carried item rather than only the currently eligible ones, so eligibility cannot move between the decision and the insert; a run that is no longer `created` enrolls nothing. Composition freeze then verifies rather than completes: the driver read its members before reaching it and seeds QA and stamps release against that list, so a member arriving at freeze would execute unseeded, and freeze refuses by name instead. An item-less environment run on a v2 flow enrolls like any other, and deliberate member choices — an explicit `progress` intent included — are never rewritten. Three cases refuse instead of enrolling: a carried item whose project or stage this run cannot admit (named with its recovery), underivable attribution or an unattributed commit (needs `composition_resolution`, above), and a run whose members were inherited from a run that already froze them — a retry of the same candidate, marked by a member carrying a `requirement_snapshot` first — which reuses that immutable membership rather than deriving against a moved baseline.

## Table: deployment_stage_receipts

Durable executor observations for non-QA deployment-stage attempts. Events do
not substitute for this authority.

```sql
id INTEGER PRIMARY KEY
run_id TEXT NOT NULL REFERENCES deployment_runs(id)
stage_name TEXT NOT NULL
attempt_number INTEGER NOT NULL -- allocated before dispatch; increasing per run/stage
correlation_id TEXT NOT NULL -- idempotency key for one dispatch
target_kind TEXT NOT NULL -- persistent_environment | run_preview
target_name TEXT -- required when ready
status TEXT NOT NULL -- pending | ready | failed | cancelled
observed_url TEXT
observed_release_lineage TEXT -- required when ready; exact run candidate
observed_artifact_identity TEXT -- must match when the run pins an artifact
executor TEXT NOT NULL
executor_receipt TEXT
failure_reason TEXT -- required when failed or cancelled
created_at TEXT NOT NULL
completed_at TEXT -- required when ready
UNIQUE(run_id, stage_name, attempt_number)
UNIQUE(run_id, stage_name, correlation_id)
```

The attempt number, rather than row insertion order, determines the current
observation. A repeated correlation is accepted only with identical immutable
dispatch inputs, and a terminal callback cannot change its evidence. Scoped QA
consumes only the latest ready attempt from the QA target's earlier
`source_stage`, with the exact target and release lineage and, when the run pins
one, the exact artifact identity. A delayed older success cannot override a
newer failure, and a superseded receipt cannot revalidate an accepted execution
or later-stage prerequisite. Run-preview readiness requires an observed URL;
command-only persistent environments do not.

Who fills those observed columns is a per-target-kind decision,
registered in `deploy_pipeline_stage_receipt_producers.RECEIPT_PRODUCERS`.
Each producer takes one `ProducerContext` (the stage, its QA target, the
run and stage names, the project, the dispatch correlation id and the
dispatch callable) and returns a `StageObservation`: target name,
observed release lineage, optionally an observed URL and artifact
identity. The step runner's diagnostic travels to `executor_receipt`
instead, so a producer that reads a served URL and commit back reports
them structurally rather than encoding them in one string. An empty
observed-identity column is not a gap to fill with whatever string is at
hand — the store compares observed against pinned, so an invented value
refuses the receipt, and a run pinning an artifact identity no producer
reads back is refused before the stage dispatches. The registry's key
set *is* the supported-target-kind list.

Release verification and notices — how release-to-done reads both QA
authorities, who observes a stage receipt, and the verdict and owner
notices — live in [release-delivery.md](release-delivery.md).

## Table: deployment_run_items

Membership table linking items to deployment runs. Zero rows for a run are valid when the run is an environment-level deploy with no attached backlog item; do not infer failure from item-less membership after the run has started executing.

```sql
run_id TEXT NOT NULL REFERENCES deployment_runs(id)
item_id INTEGER NOT NULL -- backlog item numeric ID
added_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
delivery_intent TEXT -- progress | final
requirement_selection TEXT -- explicit member requirement/plan IDs selected for admission
requirement_snapshot TEXT -- full selected requirement, plan, case, and attachment content
PRIMARY KEY (run_id, item_id)
```

Item-bound delivery starts from `/yoke usher PREFIX-N` or `yoke deployment-runs start-for-item`, which creates the run and inserts membership rows. For repeated continuous-slice delivery, intent is `progress` until the workflow's final predecessor and `final` at that final delivery posture. Member admission accepts explicit repeated `--requirement-id` and `--plan-id` selections; it never rolls every item requirement into a release by default. Membership is participation, not completion: a same-project item may ride a run whose flow is not its selected (or project-default) completion flow, and that run still enforces its own QA and approvals. Item completion, Dash deploy-after-merge, done-transition evidence, and the delivery-evidence fact read only the newest run on that selected flow. An empty unresolved flow is merge-only — no completion run exists.

### The deploy lock gates create and execute

Creating a run (`deployment_runs.create`, `deployment_runs.start_for_item`) and executing one (`deployment-runs execute`, and the item form of the same pipeline) each refuse unless the calling session holds the project's deploy lock — the `deploy_serialization` coordination claim addressed by `DEPLOY:<project-slug>`. One driver owns a project's deployments, so a stage promotion cannot overtake the production promotion it precedes. Take it before the pair and release it after:

```text
yoke claims coordination-claim acquire --project P --key DEPLOY:P --reason "driving the release pair"
yoke claims coordination-claim release --project P --key DEPLOY:P --reason "release pair complete"
```

It is per project rather than per environment because a release pair deploys stage and production from one pinned source; both halves run under one hold, so no second driver slips between them. The steering seat takes it when it starts driving a pair and releases it when the pair completes. Refusals name the current holder, the acquire recipe, and the release recipe.

The kind is sticky: nothing reclaims the lock automatically, because a pipeline whose local driver died is still running on CI. After confirming the pipeline has settled, list the live claim and review its holder, then use the signed-in human action outside any harness session to free the exact stranded row with `yoke coordination-claim release --project P --key DEPLOY:P --claim-id N --holder-session-id S --reason "..."`. Manual and launched agent sessions are refused. This registered action works over HTTPS or local authority, requires project `claims.release` permission, refuses if the claim or holder changed after review, and records a WARN `OperatorLeaseRelease` plus the durable reason on the claim row.

Exclusivity is on `project_id` alone. The slug rides in the claim scope so the operator key renders without a database read, and renaming a project cannot hand out a second live lock.

A claim row is session-bound by foreign key, so there is no session-less deploy lock: a caller that resolves no harness session is refused and told the same recovery every claim-holding operation names — run it from a harness session, or, for an operator driving the deploy from a plain terminal, register one (`yoke sessions begin --help`) and point `$YOKE_SESSION_ID` at it so the acquire and the run share one holder.

Claim storage, stickiness, and the board rendering for every coordination kind: the "Shared-operation coordination claims" section of [`qa-and-sessions.md`](qa-and-sessions.md).

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

### Blocking QA holds the succeeded stamp

A run does not reach `status='succeeded'` while any blocking QA
obligation is unresolved. `deployment_runs.cmd_update` is the boundary
that enforces it, so every route into a succeeded stamp — including the
pipeline's own finalization — is covered by one check.

Two tables carry those obligations, and both are read:

- `deployment_run_qa`, the flow-derived checks. Only `passed` and
  `waived` resolve one. `failed` does not: a failed blocking check is
  the strongest reason not to call the run succeeded.
- `qa_requirements` rows keyed by `deployment_run_id`, the run's plan
  cases. One resolves on a `qa_runs` row with `verdict='pass'`, or on a
  waiver. A case whose latest run is `undetermined` and awaits human
  evidence review is named with that pending review and its authorities.

Non-blocking checks never hold a run, and `force=True` overrides the
hold exactly as it overrides the stage checks beside it.

The pipeline reports this before it tries the write, so the operator
reads the specific unresolved obligations rather than a refusal from
the status update. It stamps `current_stage='complete'`, prints each
obligation, and exits 5 without emitting `DeploymentRunSucceeded` or a
`completed_at`. The stages already executed keep their recorded results.
Settle or waive each obligation and re-drive the run: the pipeline
resumes at `complete`, skips every stage, and finalizes.

Owner: `yoke_core.domain.deployment_run_completion_preconditions`.

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
