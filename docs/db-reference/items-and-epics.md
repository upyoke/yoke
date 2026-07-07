# DB Reference — Items and Epic Tables

Schemas for backlog items, epic tasks, and the supporting shepherd / caveat / dependency tables. Cross-link back from [db-reference.md](../db-reference.md) for entry points, the domain catalog, timestamp discipline, JSON-payload conventions, qa CLI, body write path, common pitfalls, and the status lifecycle reference.

## Backlog ontology

Backlog items are flat rows in `items` — there is no parent-child column or table relating one item to another. An epic is just an item whose `type='epic'`. Standalone issues are not child rows of any epic; epic decomposition lives in the separate `epic_tasks` table.

Epic tasks are keyed by `(epic_id, task_num)`. The `epic_id` foreign key IS the epic item's own numeric `items.id` — for an epic item, `epic_tasks.epic_id` and the epic's `items.id` are the same value. There is no parent-link column on `items`. Resolve an epic backlog item by `id` (with `type='epic'` for safety); resolve its task rows through `epic_tasks.epic_id`.

When an epic is synced to GitHub, sync may create one parent issue plus one task issue per `epic_tasks` row. That GitHub-side parent issue is metadata for `epic_tasks` sync, not a relationship in `items`.

## Table: items

```sql
id INTEGER PRIMARY KEY
title TEXT NOT NULL -- max 100 chars (enforced by the backlog service)
type TEXT NOT NULL DEFAULT 'issue' -- epic | issue
status TEXT NOT NULL DEFAULT 'idea' -- Epic: idea|refining-idea|refined-idea|planning|plan-drafted|refining-plan|planned|implementing|reviewing-implementation|reviewed-implementation|polishing-implementation|implemented|release|done + Issue-workflow-type: idea|refining-idea|refined-idea|implementing|reviewing-implementation|reviewed-implementation|polishing-implementation|implemented|release|done + Exceptional: cancelled|blocked|stopped|failed
priority TEXT NOT NULL DEFAULT 'medium' -- high|medium|low
flow TEXT DEFAULT 'accelerated'
rework_count INTEGER DEFAULT 0
frozen INTEGER DEFAULT 0
github_issue TEXT
deployed_to TEXT
worktree TEXT
body TEXT
merged_at TEXT
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
source TEXT NOT NULL DEFAULT '2' -- stringified actors.id for who/what originated the item
owner TEXT -- stringified actors.id for who owns intent, tradeoffs, and acceptance
project TEXT NOT NULL DEFAULT 'yoke' -- FK → projects(id); which project this item targets
deployment_flow TEXT -- FK → deployment_flows(id); assigned deployment flow
deploy_stage TEXT -- current stage in the deployment flow (NULL = not started)
spec TEXT -- PM spec content
design_spec TEXT -- design spec content
technical_plan TEXT -- architect technical plan
worktree_plan TEXT -- worktree/epic task plan
shepherd_log TEXT -- shepherd transition log
shepherd_caveats TEXT -- shepherd caveats summary
test_results TEXT -- test/QA results
deploy_log TEXT -- deployment log
browser_qa_metadata TEXT -- → JSONB on Postgres; validated JSON object (browser_testable, visual_outcome, browser_routes, browser_timing_hints_ms); populated at idea time, corrected by refine, consumed by browser QA seeding
db_mutation_profile TEXT -- → JSONB on Postgres; validated JSON object declaring governed DB mutation (state, model_name, mutation_intent, migration_modules, compatibility_class, ...); default '{"state":"none"}'. Internal half of the unified DB claim — write through `db-claim-amend`, never raw
db_compatibility_attestation TEXT -- → JSONB on Postgres; validated JSON object carrying the safety argument (frozen_at, pre_merge_readers_writers, invariants, rehearsal_commands, residual_risk_notes, rehearsal_outcomes, class_escalations); default '{}'. Internal half of the unified DB claim — write through `db-claim-amend`, never raw
spec_updated_at TEXT -- timestamp of last spec field update
spec_updated_by TEXT -- agent/user that last updated spec
resolution TEXT -- resolution type (e.g., 'completed', 'duplicate', 'wontfix')
resolution_ref TEXT -- reference for resolution (e.g., duplicate item ID)
resolution_comment TEXT -- free-text resolution notes
```

> **Status enum note:** Two progressions exist, selected by item type. **Issue-workflow-type:** `idea|refining-idea|refined-idea|implementing|reviewing-implementation|reviewed-implementation|polishing-implementation|implemented|release|done`. **Epic:** `idea|refining-idea|refined-idea|planning|plan-drafted|refining-plan|planned|implementing|reviewing-implementation|reviewed-implementation|polishing-implementation|implemented|release|done`. Exceptional states (`cancelled|stopped|failed`) are reachable from multiple points in both progressions.

**Structured-field CLI examples** (body renders on next read):

```sh
python3 -m yoke_core.cli.db_router items get YOK-N spec
printf '%s' "$CONTENT" | python3 -m yoke_core.cli.db_router items update 42 spec --stdin
python3 -m yoke_core.cli.db_router sections upsert 42 "Goals" --content-file /tmp/g.md --ordering 100
python3 -m yoke_core.domain.item_field_transform section-upsert --item YOK-N --section "Goals" --body-file /tmp/g.md --ordering 100 --source operator
```

> **Blocked is a flag on items.** Columns `items.blocked INTEGER DEFAULT 0` and `items.blocked_reason TEXT` carry the operator-set block; lifecycle status is preserved across block/unblock; legacy `status='blocked'` lifecycle position is retired (`HC-blocked-status-drift` flags any survivor). Operators use `/yoke block YOK-N "<reason>"` / `/yoke unblock YOK-N`. Epic-task `blocked` is unchanged. The view column `item_progress_view.blocked_reason` is `pipeline_blocked_reason`. Full architectural-why: [`docs/archive/decisions/blocked-flag-retirement.md`](../archive/decisions/blocked-flag-retirement.md).

### DB Claim — the unified amendment workflow

`db_mutation_profile` and `db_compatibility_attestation` are two JSON columns on the `items` table (not standalone tables) — the two storage halves of one operator-facing concept: the item's **DB claim**. The claim says (a) what governed DB mutation the ticket performs and (b) the safety argument for why pre-merge `main` stays true after it lands.

The canonical write surface is the `db_claim.amend` function id (see [functions.md](functions.md)). Operator/debug CLI adapter: `python3 -m yoke_core.api.service_client db-claim-amend`. Every Yoke command that needs to write or correct a claim — `/yoke idea` late classification, `/yoke refine` stale-claim repair, `/yoke advance` and `/yoke polish` mid-implementation discovery — routes through this function id. Per-field writes via `python3 -m yoke_core.cli.db_router items update <id> db_mutation_profile ...` remain structurally valid but are reserved as internal implementation helpers; do not author them in skill prose, recovery messages, or operator-facing docs.

The amendment workflow accepts a single flat payload combining both halves:

```json
{
  "state": "declared",
  "model_name": "primary",
  "mutation_intent": "apply",
  "migration_modules": ["add_items_due_date"],
  "migration_strategy": "additive_only",
  "migration_strategy_justification": "Adds nullable due_date; existing readers keep working.",
  "compatibility_class": "pre_merge_safe",
  "schema_kinds": ["additive"],
  "affected_surfaces": [{"table": "items", "columns": ["due_date"]}],
  "pre_merge_readers_writers": [{"path": "runtime/api/domain/items.py", "role": "writer"}],
  "invariants": ["items.due_date nullable after apply"],
  "rehearsal_commands": ["python3 -m yoke_core.tools.watch_pytest -- runtime/api/"],
  "residual_risk_notes": "none"
}
```

For `state="declared"` + `mutation_intent="apply"`, `migration_strategy` is required inline. For `state="declared"` + `compatibility_class="pre_merge_safe"`, the four authored attestation fields (`pre_merge_readers_writers`, `invariants`, `rehearsal_commands`, `residual_risk_notes`) are required inline. `pre_merge_readers_writers[].role` accepts only `reader` or `writer`; migration modules and schema-changing files use `writer`, not prose such as `schema migration`. The validator demultiplexes the payload across both stored fields and writes them atomically — partial writes that leave the two halves out of sync are not possible.

Negative claims — the reviewed-none decision — use the convenience flag:

```bash
python3 -m yoke_core.api.service_client db-claim-amend \
  --item YOK-N --state none --reason "<why>"
```

Running this is an **explicit reviewed-none decision**: an operator or agent has confirmed the ticket does not mutate a governed authoritative DB. The amendment stamps the reviewed-negative attestation onto the stored profile itself — `{"state":"none","reviewed_negative":true,"validated_at":"<ts>"}` — so the decision lives as item state, not in the events ledger. The prose-vs-claim gate reads that attestation as proof the negative claim was deliberately reviewed (not the implicit schema default) and clears vocabulary- and structural-trigger hits alike. Meta-tickets about DB governance that unavoidably cite `ALTER TABLE`, `ADD COLUMN`, `DROP COLUMN`, `migration_audit`, or similar DDL-shape terms advance once the reviewed-none amendment is on record. The `reviewed_negative` / `validated_at` keys are workflow-managed — amendment payloads that try to supply them are rejected as reserved.

Every successful amendment also emits a `DbClaimAmended` telemetry event whose envelope carries the previous and new claim summaries, the actor/session, and the operator-supplied reason. The event stream is history/audit-only — the gate-consulted attestation lives on the profile:

```bash
yoke events query --event-name DbClaimAmended
```

**Structural invariants:**

- `state="none"` claims stay mutable forever — the freeze stamp applies only when the workflow writes `state="declared"`.
- The amendment workflow is the sole forward writer of `db_compatibility_attestation.frozen_at` for declared claims.
- A prose-vs-claim consistency gate (`GATE_DB_CLAIM_PROSE_MISMATCH`) blocks every refine advance, evidence gate, and polish gate when the spec/body declares governed DB work but the stored profile is still the bare `state="none"` default **without** the reviewed-negative attestation. The block points at `db-claim-amend` for recovery; running the amendment workflow with `--state none --reason "<why>"` is the canonical fix for meta-tickets that legitimately discuss governance vocabulary. Backtick-wrapping DDL verbs or scrubbing terminology from the spec is **not** the canonical remediation.
- The reviewed-none signal reads the **stored profile JSON** (`state="none"` + `reviewed_negative: true`). The latest amendment is authoritative by construction — a later `state="declared"` amendment replaces the profile and removes the attestation. Malformed profile JSON, the bare implicit default, `reviewed_negative` values other than `true`, and declared states all read as not-reviewed — the gate behaves as if no amendment ever ran.
- Rows with `state="none"` + a stamped `frozen_at` are accepted as inert compatibility data; the renderer does not surface them, and the joint gate does not add new ones.

The rendered item body presents both halves as one `## DB Claim` section — internal storage stays split because the per-field validators use the column names, but operators see one DB-claim concept.

### deploy_stage: The Post-Merge Pipeline Tracker

The `deploy_stage` column tracks an item's position within its assigned deployment flow's stage sequence. It is distinct from `status` -- an item at `status=release` may be at any deploy_stage within its flow. Stage authority lives on the `deployment_runs` row (`current_stage`); `deploy_stage` is a compatibility cache.

**Key semantics:**
- `NULL` -- item has not entered the deployment pipeline (no flow assigned, or flow not yet started)
- Stage name (e.g., `prod-deploy`, `smoke`, `complete`) -- the current or last-completed stage from the item's `deployment_flow.stages` JSON array
- `needs-capability` -- pipeline halted because a required capability (SSH, Docker, etc.) is missing or misconfigured. The `deployment_runs` table records the halt via run status. Operator configures the capability, then re-runs the Usher to resume.
- `awaiting-approval` -- pipeline halted at a `human-approval` gate. Operator approves via `/yoke approve YOK-N`, then re-runs the Usher to resume.
- `complete` -- all stages in the flow have been executed successfully; the item is ready to transition to `done`

## Table: item_sections

Stores named sections of item content for flexible body generation. Each section is keyed by `(item_id, section_name)` and has an ordering field for controlling render sequence.

```sql
item_id INTEGER NOT NULL -- FK → items(id)
section_name TEXT NOT NULL -- section identifier (e.g., "Goals", "Design Spec")
content TEXT -- section content (Markdown)
ordering INTEGER -- render order (lower = earlier)
created_at TEXT NOT NULL -- ISO 8601 timestamp
updated_at TEXT NOT NULL -- ISO 8601 timestamp
PRIMARY KEY (item_id, section_name)
```

## Table: shepherd_verdicts

```sql
id INTEGER PRIMARY KEY
item TEXT NOT NULL
transition TEXT NOT NULL
worker TEXT NOT NULL
verdict TEXT NOT NULL
caveats TEXT
attempt INTEGER DEFAULT 1
created_at TEXT NOT NULL
```

## Table: caveat_dispositions

Tracks what happened to each caveat during Shepherd's step 5i triage (RESOLVED or DEFERRED). The UNIQUE constraint includes `attempt` to support rework/retry scenarios where the same transition fires multiple times. Created by Migration 3.

```sql
id INTEGER PRIMARY KEY
item TEXT NOT NULL -- YOK-N reference
transition TEXT NOT NULL -- e.g. refined_idea_to_planning
attempt INTEGER NOT NULL DEFAULT 1
caveat_num INTEGER NOT NULL
caveat_text TEXT NOT NULL
disposition TEXT NOT NULL -- RESOLVED | DEFERRED
resolution_details TEXT
verdict_id INTEGER -- FK -> shepherd_verdicts(id)
created_at TEXT NOT NULL
FOREIGN KEY (verdict_id) REFERENCES shepherd_verdicts(id)
UNIQUE(item, transition, attempt, caveat_num)
```

Index: `idx_cd_item ON caveat_dispositions(item)`

Valid `disposition` values: `RESOLVED`, `DEFERRED`.

## Table: item_dependencies

**Single source of truth for all inter-item dependencies**. Every row is a canonical enforced blocker. All dependency reads and writes go through this table via `yoke shepherd dependency-add` and `yoke shepherd dependency-list`. The `items.depends_on` column is a read-only compatibility column and should not be written to.

Cross-item dependency constraints discovered during shepherd phases. Any
remaining non-empty `depends_on` values should be cleaned by direct data
repair before that compatibility column is dropped.

```sql
id INTEGER PRIMARY KEY
dependent_item TEXT NOT NULL -- YOK-N that depends on another
blocking_item TEXT NOT NULL -- YOK-N that blocks the dependent
gate_point TEXT NOT NULL DEFAULT 'activation' -- activation | integration | closure
satisfaction TEXT NOT NULL DEFAULT 'status:done' -- status:done | status:implemented | fact:merged
source TEXT NOT NULL -- shepherd | conduct | operator | migration | feed
session_id INTEGER -- nullable contextual session ID
rationale TEXT NOT NULL DEFAULT '' -- human-readable explanation of the edge
evidence_json TEXT NOT NULL DEFAULT '{}' -- structured provenance payload
created_at TEXT NOT NULL
UNIQUE(dependent_item, blocking_item, gate_point)
```

`dependent_item` and `blocking_item` intentionally store public `YOK-N`
text references, not numeric `items.id` values. Prefer `yoke shepherd
dependency-list YOK-N` for routine dependency reads instead of ad hoc SQL
that compares these columns to bare integers.

Indexes:
- `idx_id_dependent ON item_dependencies(dependent_item)`
- `idx_id_blocking ON item_dependencies(blocking_item)`

Constraints:
- `UNIQUE(dependent_item, blocking_item, gate_point)` -- a given pair of items can have at most one dependency at each gate point. Inserts use idempotent `ON CONFLICT DO NOTHING` semantics so re-declaring the same dependency is a silent no-op.

Valid `source` values: `shepherd`, `conduct`, `operator`, `migration`, `feed`.

### Canonical blocker model

Every row in `item_dependencies` is a real enforced blocker with directional meaning: `dependent_item` cannot pass the relevant gate until `blocking_item` satisfies the declared condition.

**Gate point** (`gate_point`) -- *when* in the dependent's lifecycle the dependency is enforced:
- `activation` -- do not start the dependent yet (checked before advancing to `implementing`)
- `integration` -- may work in parallel, but the dependent must land (merge) after the blocker
- `closure` -- the dependent may not be considered complete until the blocker reaches a milestone

**Satisfaction condition** (`satisfaction`) -- *what* must be true about the blocker:
- `status:done` -- blocking item must reach `done` status
- `status:implemented` -- blocking item must reach `implemented`, `release`, or `done`
- `fact:merged` -- blocking item's merge must be confirmed by canonical fact (`merged_at`), branch ancestry when available, or `release`/`done` status as the weakest fallback

**Explanation fields**:
- `rationale` -- short human-readable reason for the edge (e.g., "Operator-declared activation dependency")
- `evidence_json` -- structured evidence/provenance payload (e.g., `{"created_by":"operator"}`)

**Domain modules:**
- `runtime/api/domain/dependencies.py` -- low-level dependency evaluation primitives (`evaluate_satisfaction()`, `query_unsatisfied_at_gate()`, `query_frontier_blocks()`, `explain_dependency()`).
- `runtime/api/domain/dependency_planning.py` -- shared dependency-planning kernel. All gate consumers share this single module for both gate evaluation and ordered planning. Key functions:
 - `evaluate_item_gate(conn, item_id, gate_point)` -- evaluate all dependencies for one item at one gate point; returns `ItemGateEvaluation` with structured `BlockerDetail` for each unsatisfied dependency.
 - `evaluate_batch_gates(conn, gate_point)` -- batch-evaluate all dependencies at a gate point for frontier computation.
 - `plan_candidate_set(conn, candidate_ids, gate_point)` -- plan a candidate set; returns eligible items in topological order and blocked items with detail.
- Service-client commands: `python3 -m yoke_core.api.service_client evaluate-gate <item-id> <gate-point>` and `python3 -m yoke_core.api.service_client plan-candidates <gate-point> <item1> ...` delegate to the Python kernel.

**Enforcement:** `python3 -m yoke_core.domain.check_hard_blocks` evaluates satisfaction conditions per dependency with an optional `--gate-point` filter. `advance`, `conduct`, and `usher` gates use the shared kernel through that CLI or the service-client dependency commands. The frontier computation in `frontier.py` uses `evaluate_batch_gates()` from the shared kernel for activation-gate evaluation.

## Table: ouroboros_entries

```sql
id INTEGER PRIMARY KEY
timestamp TEXT NOT NULL
agent TEXT NOT NULL
context TEXT
category TEXT NOT NULL
body TEXT NOT NULL
reviewed_at TEXT
archived_at TEXT
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
```

## Table: wrapup_reports

```sql
id INTEGER PRIMARY KEY
session_timestamp TEXT NOT NULL UNIQUE -- ISO 8601 timestamp identifying the session
body TEXT NOT NULL -- full wrapup report content (Markdown)
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
```

## Table: epic_tasks

```sql
id INTEGER PRIMARY KEY
epic_id INTEGER NOT NULL
task_num INTEGER NOT NULL
title TEXT -- max 100 chars (enforced by the epic CLI)
worktree TEXT
context_estimate TEXT -- S|M|L|XL
dependencies TEXT -- comma-separated task nums
status TEXT DEFAULT 'planning' CHECK(status IN ('planning','plan-drafted','refining-plan','planned','implementing','reviewing-implementation','reviewed-implementation','polishing-implementation','implemented','release','done','failed','blocked','stopped'))
dispatch_attempts INTEGER DEFAULT 0
body TEXT
github_issue TEXT
branch TEXT
worktree_path TEXT
blocked_by TEXT
max_attempts INTEGER DEFAULT 5
agent_id TEXT
last_heartbeat TEXT
UNIQUE(epic_id, task_num)
```

> **Status enum note:** The canonical task status values are `planning|plan-drafted|refining-plan|planned|implementing|reviewing-implementation|reviewed-implementation|polishing-implementation|implemented|release|done|failed|blocked|stopped`. The DDL default is `'planning'`.

## Table: epic_task_files

```sql
id INTEGER PRIMARY KEY
epic_id INTEGER NOT NULL
task_num INTEGER NOT NULL
file_path TEXT NOT NULL
action TEXT -- create|modify|delete
FOREIGN KEY (epic_id, task_num) REFERENCES epic_tasks(epic_id, task_num)
```

## Table: epic_dispatch_chains

```sql
id INTEGER PRIMARY KEY
epic_id INTEGER NOT NULL
worktree TEXT NOT NULL
worktree_path TEXT
queue TEXT -- JSON array of task nums
current_index INTEGER DEFAULT 0
current_task TEXT
current_attempt INTEGER DEFAULT 1
max_attempts INTEGER DEFAULT 5
no_chain INTEGER DEFAULT 0
started_at TEXT
last_updated TEXT
UNIQUE(epic_id, worktree)
```

## View: item_progress_view

Read model for item delivery progress. Joins `items`, `deployment_flows`, and (when present) `deployment_runs` / `deployment_run_items` to project a single-row progress summary per item. Created by `python3 -m yoke_core.cli.db_router flows init`.

```sql
-- Fields returned per item:
item_id INTEGER -- items.id
status TEXT -- current item status
flow_name TEXT -- deployment_flows.name (NULL if no flow assigned)
run_id TEXT -- deployment_runs.id (NULL if no active run or table missing)
current_stage TEXT -- deployment_runs.current_stage (NULL if no run)
target_env TEXT -- deployment_flows.target_env (NULL if not set)
stage_progress TEXT -- 'N/M' format (NULL if no run)
done_description TEXT -- deployment_flows.done_description (NULL if no flow)
qa_summary TEXT -- latest QA run result summary (NULL if none)
blocked_reason TEXT -- blocking condition description (NULL if not blocked)
```

**Graceful degradation:** When `deployment_runs` table does not exist, the view is created with NULL for all run-specific fields (run_id, current_stage, stage_progress, blocked_reason). The view is re-created idempotently on each `python3 -m yoke_core.cli.db_router flows init` call, using Postgres schema introspection to detect schema availability.

**Queried by:** `python3 -m yoke_core.cli.db_router items progress <id>` (routed to `python3 -m yoke_core.cli.db_router items`).

## Table: epic_progress_notes

```sql
id INTEGER PRIMARY KEY
epic_id INTEGER NOT NULL
task_num INTEGER NOT NULL
note_num INTEGER NOT NULL
body TEXT
commit_hash TEXT
synced_to_github INTEGER DEFAULT 0
created_at TEXT NOT NULL
UNIQUE(epic_id, task_num, note_num)
```
