# DB Reference — Items and Epic Tables

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Items](../index.md) > Item model
<!-- /yoke:breadcrumbs -->

Raw item reads join `item_refs r ON r.item_id = items.id` and select `r.public_ref`. The read-only view follows prefix updates; `project_sequence` alone is ambiguous across projects. An `item_id` is always the integer `items.id`, never the number in the item's ref. `yoke db read` warns when the result omits both `public_ref` and `public_item_prefix`.

Schemas for backlog items, epic tasks, and the supporting shepherd / caveat / dependency tables. Read [database reference](../../databases/reference.md) for entry points, the domain catalog, JSON-payload conventions and common pitfalls; [timestamp discipline](../../databases/migrations.md#timestamp-discipline) for timestamp conventions; [QA CLI](../../verification/qa-cli.md) and [body writes](body-writes.md) and [status lifecycle](../../workflows/model/statuses.md) for those contracts.

## Backlog ontology

Backlog items are flat rows in `items` — there is no parent-child column or
table relating one item to another. A pinned workflow whose
`generated_children` policy creates task graphs stores decomposition in
`epic_tasks`; workflow names alone do not determine that policy. The
planning step creates those task rows, so never file separate child items
for an Epic's tasks.

Epic tasks are keyed by `(epic_id, task_num)`. The `epic_id` foreign key IS
the Epic item's own numeric `items.id`. There is no parent-link column on
`items`. Resolve the backlog item by `id` and verify its immutable workflow
pin; resolve its task rows through `epic_tasks.epic_id`.

When an epic is synced to GitHub, sync may create one parent issue plus one task issue per `epic_tasks` row. That GitHub-side parent issue is metadata for `epic_tasks` sync, not a relationship in `items`.

## Table: items

```sql
id INTEGER PRIMARY KEY
title TEXT NOT NULL -- length capped by the project's title policy
workflow_id TEXT NOT NULL REFERENCES workflows(id)
workflow_version_id INTEGER NOT NULL REFERENCES workflow_versions(id)
workflow_posture TEXT NOT NULL DEFAULT '{}'
status TEXT NOT NULL -- current stage in the pinned definition
priority TEXT NOT NULL DEFAULT 'medium' -- high|medium|low
frozen INTEGER DEFAULT 0
github_issue TEXT
deployed_to TEXT
body TEXT
merged_at TIMESTAMPTZ -- the landing merge commit's own time; a second landing replaces it. Every landing is kept in `item_landings` ([item-landings.md](landings.md))
created_at TIMESTAMPTZ NOT NULL
updated_at TIMESTAMPTZ NOT NULL
source TEXT NOT NULL DEFAULT '2' -- stringified actors.id for who/what originated the item
owner TEXT -- stringified actors.id for who owns intent, tradeoffs, and acceptance
project_id INTEGER NOT NULL REFERENCES projects(id) -- explicit attribution; no default
deployment_flow TEXT -- FK → deployment_flows(id); assigned deployment flow
deploy_stage TEXT -- current stage in the deployment flow (NULL = not started)
spec TEXT -- PM spec content
design_spec TEXT -- design spec content
technical_plan TEXT -- architect technical plan
worktree_plan TEXT -- worktree/epic task plan
shepherd_caveats TEXT -- shepherd caveats summary
test_results TEXT -- test/QA results
deploy_log TEXT -- deployment log
db_mutation_profile TEXT -- → JSONB on Postgres; validated JSON object declaring governed DB mutation (state, model_name, mutation_intent, migration_modules, compatibility_class, ...); default '{"state":"none"}'. Internal half of the unified DB claim — write through `db-claim-amend`, never raw
db_compatibility_attestation TEXT -- → JSONB on Postgres; validated JSON object carrying the safety argument (frozen_at, pre_merge_readers_writers, invariants, rehearsal_commands, residual_risk_notes, rehearsal_outcomes, class_escalations); default '{}'. Internal half of the unified DB claim — write through `db-claim-amend`, never raw
spec_updated_at TIMESTAMPTZ -- timestamp of last spec field update
spec_updated_by TEXT -- agent/user that last updated spec
resolution TEXT -- resolution type (e.g., 'completed', 'duplicate', 'wontfix')
resolution_ref TEXT -- reference for resolution (e.g., duplicate item ID)
resolution_comment TEXT -- free-text resolution notes
```

> **Stage authority:** The immutable workflow version owns ordered stages,
> terminal stages, gates, policies, and skill bindings. Read it with
> `yoke workflows item get PREFIX-N`, then `yoke workflows version get WORKFLOW VERSION`; transition code loads the item's explicit
> version pin rather than a status table in this document.

Structured item mutations use the registered [function surfaces](../../functions/index.md).
Read `yoke items structured-field --help` before replacing or transforming fields.

> **Blocked is a flag on items.** Columns `items.blocked INTEGER DEFAULT 0` and `items.blocked_reason TEXT` carry the operator-set block; lifecycle status is preserved. The flag is for waits with no unsatisfied blocking edge: `items.block` refuses while an activation/integration/closure edge is unsatisfied and names only unsatisfied blockers. Wait for the blocking item, or remove the edge with `yoke items dependency remove`; satisfied edges permit an unrelated hold. Operators use `yoke items block PREFIX-N --reason TEXT` / `yoke items unblock PREFIX-N`. Epic-task `blocked` is unchanged. View column `item_progress_view.blocked_reason` is `pipeline_blocked_reason`. Architectural-why: `docs/archive/decisions/blocked-flag-retirement.md`.

### DB Claim: the unified amendment workflow

`db_mutation_profile` and `db_compatibility_attestation` are two JSON columns on the `items` table (not standalone tables) — the two storage halves of one operator-facing concept: the item's **DB claim**. The claim says (a) what governed DB mutation the work item performs and (b) the safety argument for why pre-merge `main` stays true after it lands.

The canonical writer is `db_claim.amend` (see [claims.md](../../functions/claims.md)).
Use `yoke db-claim amend PREFIX-N --reason TEXT --payload-file /tmp/claim.json`;
read its `--help` for the flat payload and reviewed-none form. Idea, Refine,
Implement and Polish use the same atomic writer when classification changes.
Do not write either storage half independently.

The amendment workflow accepts a single flat payload combining both halves:

```json
{
  "state": "declared",
  "model_name": "primary",
  "mutation_intent": "apply",
  "migration_modules": ["backfill_items_due_date"],
  "migration_strategy": "additive_only",
  "migration_strategy_justification": "Fills missing due_date values; existing readers keep working.",
  "compatibility_class": "pre_merge_safe",
  "schema_kinds": [],
  "data_kinds": ["fill"],
  "affected_surfaces": [{"table": "items", "columns": ["due_date"]}],
  "pre_merge_readers_writers": [{"path": "src/<package>/items.py", "role": "writer"}],
  "invariants": ["Every items row has due_date after apply"],
  "rehearsal_commands": ["yoke watch pytest -- <project-test-path>"],
  "residual_risk_notes": "none"
}
```

For `state="declared"` + `mutation_intent="apply"`, `migration_strategy` is required inline. For `state="declared"` + `compatibility_class="pre_merge_safe"`, the four authored attestation fields (`pre_merge_readers_writers`, `invariants`, `rehearsal_commands`, `residual_risk_notes`) are required inline. `rehearsal_commands` are test commands that rehearsal runs against the validation database, such as a focused pytest run; never list `yoke migration rehearse` there, because rehearsal would call itself and fail. `pre_merge_readers_writers[].role` accepts only `reader` or `writer`; migration modules and schema-changing files use `writer`, not prose such as `schema migration`. The validator demultiplexes the payload across both stored fields and writes them atomically — partial writes that leave the two halves out of sync are not possible.

Negative claims — the reviewed-none decision — use the convenience flag:

```bash
yoke db-claim amend PREFIX-N --state none --reason "<why>"
```

Running this records an **explicit reviewed-none decision** on the stored profile:
`{"state":"none","reviewed_negative":true,"validated_at":"<ts>"}`.
Those keys are workflow-managed; amendment payloads cannot supply them.
The stamps are inert data. The gate checks migration files, so a reviewed-none
decision does not excuse new migration entries.

A schema-only additive change (a net-new table, index or column in the schema
module, which boot converges) has no migration entry; record
`yoke db-claim amend PREFIX-N --state none --reason "..."`.

A successful amendment also records a `DbClaimAmended` telemetry event whose envelope carries the previous and new claim summaries, the actor/session, and the operator-supplied reason. That event is disposable: it is written best-effort alongside the amendment and a severity filter, an events outage, or retention expiry drops it without touching the decision. The event stream is history/audit-only — the reviewed decision lives on the profile:

```bash
yoke events query --event-name DbClaimAmended
```

**Structural invariants:**

- `state="none"` claims stay mutable forever — the freeze stamp applies only when the workflow writes `state="declared"`.
- The amendment workflow is the sole forward writer of `db_compatibility_attestation.frozen_at` for declared claims.
- `new_migrations_need_db_claim` compares every configured `migration_model` history in the item's local lane against the integration target. Lane-only numbered entries require `state="declared"`; refusals list the files and `yoke db-claim amend PREFIX-N` recovery. Review entry, `yoke merge item --check`, and merge preflight check this. No capability or no new entries passes; a host without the lane skips the local inspection. Declared apply claims retain ordering and collision checks.
- Release and boot refuse while an open item or current workflow names the retired DB claim gate. Use `yoke workflows item migrate PREFIX-N` on the running build for affected items, or `yoke workflows current set` for current versions, then retry. Terminal items retain their historical pins.
- Rows with `state="none"` + a stamped `frozen_at` are accepted as inert compatibility data; the renderer does not surface them, and the joint gate does not add new ones.

The rendered item body presents both halves as one `## DB Claim` section — internal storage stays split because the per-field validators use the column names, but operators see one DB-claim concept.

### deploy_stage: The Post-Merge Pipeline Tracker

The `deploy_stage` column tracks an item's position within its assigned deployment flow's stage sequence. It is distinct from `status` -- an item at `status=release` may be at any deploy_stage within its flow. Stage authority lives on the `deployment_runs` row (`current_stage`); `deploy_stage` is a compatibility cache.

**Key semantics:**
- `NULL` -- item has not entered the deployment pipeline (no flow assigned, or flow not yet started)
- Stage name (e.g., `prod-deploy`, `smoke`, `complete`) -- the current or last-completed stage from the item's `deployment_flow.stages` JSON array
- `needs-capability` -- pipeline halted because a required capability (SSH, Docker, etc.) is missing or misconfigured. The `deployment_runs` table records the halt via run status. Operator configures the capability, then re-runs the Usher to resume.
- `awaiting-approval` -- pipeline halted at a `human-approval` gate. Operator approves via `/yoke approve PREFIX-N`, then re-runs the Usher to resume.
- `complete` -- all stages in the flow have been executed successfully; the item is ready to transition to `done`

## Table: item_sections

Stores named sections of item content for flexible body generation. Each section is keyed by `(item_id, section_name)` and has an ordering field for controlling render sequence.

```sql
item_id INTEGER NOT NULL -- FK → items(id)
section_name TEXT NOT NULL -- section identifier (e.g., "Goals", "Design Spec")
content TEXT -- section content (Markdown)
ordering INTEGER -- render order (lower = earlier)
created_at TIMESTAMPTZ NOT NULL -- ISO 8601 timestamp
updated_at TIMESTAMPTZ NOT NULL -- ISO 8601 timestamp
PRIMARY KEY (item_id, section_name)
```

## Table: shepherd_verdicts

```sql
id INTEGER PRIMARY KEY
public_ref TEXT -- active PREFIX-N identity; NULL for archived orphan evidence
archived_item_key TEXT -- original unresolvable key, only on archived rows
transition TEXT NOT NULL
worker TEXT NOT NULL
verdict TEXT NOT NULL
caveats TEXT
attempt INTEGER DEFAULT 1
created_at TIMESTAMPTZ NOT NULL
```

## Table: caveat_dispositions

Tracks what happened to each caveat during Shepherd's step 5i triage (RESOLVED or DEFERRED). The UNIQUE constraint includes `attempt` to support rework/retry scenarios where the same transition fires multiple times.

```sql
id INTEGER PRIMARY KEY
public_ref TEXT -- active PREFIX-N identity; NULL for archived orphan evidence
archived_item_key TEXT -- original unresolvable key, only on archived rows
transition TEXT NOT NULL -- e.g. refined_idea_to_planning
attempt INTEGER NOT NULL DEFAULT 1
caveat_num INTEGER NOT NULL
caveat_text TEXT NOT NULL
disposition TEXT NOT NULL -- RESOLVED | DEFERRED
resolution_details TEXT
verdict_id INTEGER -- FK -> shepherd_verdicts(id)
created_at TIMESTAMPTZ NOT NULL
FOREIGN KEY (verdict_id) REFERENCES shepherd_verdicts(id)
UNIQUE(public_ref, transition, attempt, caveat_num)
```

Index: `idx_cd_item ON caveat_dispositions(public_ref)`

Valid `disposition` values: `RESOLVED`, `DEFERRED`.

## Table: ouroboros_entries

```sql
id INTEGER PRIMARY KEY
timestamp TIMESTAMPTZ NOT NULL
agent TEXT NOT NULL
context TEXT
category TEXT NOT NULL -- failed | new | unclear | observation | idea
body TEXT NOT NULL -- evidence, 1–4000 characters
project_id INTEGER -- nullable observing project
actor_id INTEGER -- authenticated request actor; receiving service for public notes
reporter_email TEXT -- nullable contact email
yoke_version TEXT -- nullable sender version
universe_fingerprint TEXT -- nullable slug@timestamp; public input is untrusted
reviewed_at TIMESTAMPTZ
archived_at TIMESTAMPTZ
created_at TIMESTAMPTZ NOT NULL -- app-supplied ISO-8601 UTC; see timestamp discipline in the introduction
```


## Related

- [Generated task model](tasks.md)
- [Item dependency model](dependencies.md)
