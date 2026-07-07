# Yoke DB Reference

Source of truth: the configured Postgres authority. Agent-facing reads and
writes route through registered `yoke ...` commands or the Yoke
function-call surface. Everyday raw diagnostic SELECTs use
`yoke db read "SELECT ..."`. `python3 -m yoke_core.cli.db_router query`
remains source-dev/operator-debug break-glass only; never call raw database
clients directly and never hardcode a DB path or DSN.

Quickstart for session operators: `AGENTS.md` § Code Conventions, § Structured Item Writes, and § Governed DB Mutation. Update those sections when this file changes.

The operator-readable Atlas of the Yoke agent-facing surfaces (registered function ids, wrapped `yoke <subcommand>` adapters, permanent boundaries, pending handler-registration rows, live contradictions) lives at [`docs/atlas.md`](atlas.md). Mutation operations against the DB should reach for a registered function id first; CLI wrappers are operator/debug adapters over the same dispatched request.

This file is the **entry point**: it covers entry points, the bootstrap contract, the retired-schema registry, the domain catalog, timestamp discipline, query-time SQL clock helpers, JSON-payload columns, and common pitfalls. Per-table schema bodies, the qa CLI reference, the body write path, and the status lifecycle live in topic files under [docs/db-reference/](db-reference/).

## Common column mistakes to avoid in raw SQL

Quick reference for the columns most often mis-named in agent SQL. The DB-command column lint at `runtime/api/domain/lint_db_rules_columns.py` denies these patterns and points here; legacy telemetry/check ids remain stable.

- `epic_tasks`: use `epic_id` (NOT `item_id`), `task_num` (NOT `task_number`/`seq`), `dependencies` (NOT `depends_on`).
- `epic_progress_notes`: content is in `body` (NOT `note`).
- `events`: use `event_name`/`event_type`/`source_type`/`created_at`/`envelope` (NOT `type`/`timestamp`/`source`/`detail`/`context`/`worker`/`payload`/`outcome`).
- `deployment_runs`: use `id` (NOT `run_id`), `current_stage` (NOT `deploy_stage`), `created_by` (NOT `creator`). No `item_id` column — join through `deployment_run_items` for item-bound runs.
- `deployment_run_items`: use `run_id` + `item_id` (composite PK, NO `id` column). **Junction table only** — has NO `deploy_stage`, `current_stage`, or `status` columns. Stage data lives on `items.deploy_stage` and `deployment_runs.current_stage`. Zero rows are valid for started environment-level deployment runs.
- `qa_runs`: use `qa_requirement_id` (NOT `requirement_id` or `req_id`).
- `deployment_flows`: use `id` (NOT `flow_id`), no `item_id` column.
- `shepherd_verdicts`: use `item` (NOT `item_id`), `transition` (NOT `gate`).
- `ouroboros_entries`: content is in `body` (NOT `entry`), use `created_at` (NOT `timestamp`).
- `project_capabilities`: use `type` (NOT `capability`/`name`/`capability_type`), `config` for full JSON (may contain secrets), `settings` for non-sensitive JSON.
- `projects`: use `id` (NOT `project_id`/`name`) and `github_repo` (NOT `repo_url`/`github_url`). Checkout paths are machine-local config, not `projects` columns. Ticket-level deployment-flow defaulting lives in the `deploy_defaults` Project Structure family, not as a column on `projects`.
- **Domain names**: `epic` (NOT `epics`), `events registry` (NOT `registry`), `runs` (NOT `deploy-events`); board rebuild is `yoke board rebuild`.
- **Live-claim holder lookup** (often mis-guessed): `python3 -m runtime.harness.harness_sessions who-claims <item-id>`. Do not guess owner/session columns or retired per-item claim tables; the typed `work_claims` model uses `target_kind` plus the matching specialized columns. See [qa-and-sessions.md § Live claim-holder lookup](db-reference/qa-and-sessions.md).

## Agent-context packet

Bash-capable agents (Architect, Engineer, Tester, Simulator, Boss) receive a compact, role/topic-scoped DB Quick Reference packet that is **generated** from this reference plus live schema introspection — never hand-copied. The generator is `yoke_core.domain.schema_api_context`; the curated seed is split across `yoke_core.domain.schema_api_context_seed` (facade — role/topic assignments, stale-term regression list, size budgets), `yoke_core.domain.schema_api_context_tables` (canonical schema cheat sheet), and `yoke_core.domain.schema_api_context_commands` (wrapper-command recipes). The marker expander that wires it into rendered Claude / Codex agent adapters is `yoke_core.domain.agents_render_context`. Operator commands:

Agents render/check via the function-call surface (`packets.render`, `packets.check`, `agents.render.run`, `agents.render.check`). Operator/debug adapters (the matching CLI shapes):

```sh
yoke packets render --role main_agent
yoke packets render --role engineer_agent
yoke packets check
yoke agents render
yoke agents render check
```

When this reference changes (a new column, a renamed table, a new wrapper command), update the curated seed in lockstep; `agents_render check` will surface drift in CI when canonical or rendered agent prompts fall behind, including stale hand-authored DB/API examples that coexist with packet markers. Do not hand-author a parallel cheat sheet — the marker pair `<!-- YOKE:DB-PACKET role=R topic=T start --> ... <!-- YOKE:DB-PACKET end -->` is the only sanctioned insertion point in any agent prompt.

**Topics today:**

- `core` — control plane + structured fields (`epic_tasks`, `epic_progress_notes`, `events`) plus item-dependency wrapper recipes (`shepherd dependency-list`, `dependency-add`, `dependency-update`, `dependency-remove`).
- `claims` — `harness_sessions`, `work_claims`, `path_claims` plus the `who-claims` / `path-claim-list` / `release-work-claim` wrappers.
- `qa` — `qa_requirements`, `qa_runs`, the QA discovery wrappers (`yoke qa requirement list`, `yoke qa run list`, `yoke qa run add`), and the reviewed-implementation gate preview surfaced through `/yoke advance YOK-N reviewed-implementation`. The packet teaches that running the test suite alone does not satisfy the gate — agents must route reviewed-implementation transitions through `/yoke advance YOK-N reviewed-implementation`, never raw `items update`.
- `project` — `project_structure` aggregate plus the `command_definitions` wrappers (`get <project> <scope>`, `list <project>`, `scopes`). The packet teaches that there is no top-level `command_definitions` table — raw `... FROM command_definitions WHERE ...` queries fail; route through `yoke_core.domain.command_definitions` instead.

**Per-role topic assignments** live in `schema_api_context_seed.ROLE_TOPICS`. Role keys are layer-explicit: `main_agent`, `architect_agent`, `engineer_agent`, `tester_agent`, `simulator_agent`, and `boss_agent`. Engineer and Tester receive all four topics (they run tests, record QA verdicts, and consume project test commands). Main Agent, Architect, Simulator, and Boss receive `core` + `claims` only — they investigate, plan, trace, and review without invoking the QA gate or `command_definitions` directly. `harness_contract` is the separate manifest/bootstrap substrate contract, not a `schema_api_context` role. The doctrine is mirrored in `docs/agents.md`.

## Topic Index

- [items-and-epics.md](db-reference/items-and-epics.md) — `items`, `item_sections`, `shepherd_verdicts`, `caveat_dispositions`, `item_dependencies`, `ouroboros_entries`, `wrapup_reports`, `epic_tasks`, `epic_task_files`, `epic_dispatch_chains`, `item_progress_view`, `epic_progress_notes`. Includes the **Backlog ontology** note (items are flat rows; epic decomposition lives in `epic_tasks` keyed on `(epic_id, task_num)` where `epic_id` is the epic item's own `items.id`), the **DB Claim — unified amendment workflow**, and the `deploy_stage` cache contract.
- [qa-and-sessions.md](db-reference/qa-and-sessions.md) — `qa_requirements`, `qa_runs`, `qa_artifacts`, `release_entries`, `merge_locks`, `harness_sessions`, `work_claims`, `designs`. Includes session-offer endpoint behavior and chain checkpoint persistence.
- [projects-and-flows.md](db-reference/projects-and-flows.md) — `projects`, the Project Structure aggregate (state/entries/audit), `sites`, `environments`, `project_capabilities`, `capability_secrets`, `capability_templates`, `deployment_flows`. Includes deployment-flow defaulting rules and seed data.
- [events-and-deployments.md](db-reference/events-and-deployments.md) — `events`, `severity_config`, `event_registry`, `deployment_runs`, `deployment_run_items`, `deployment_run_qa`, `deployment_preview_environments`, `ephemeral_environments`. Includes the branch-naming contract.
- [qa-cli-and-body-write.md](db-reference/qa-cli-and-body-write.md) — qa domain CLI subcommand reference, the structured-field body write path, error propagation, project-aware GitHub sync, canonical write pattern.
- [status-lifecycle.md](db-reference/status-lifecycle.md) — issue/epic item progressions, epic-task lifecycle, valid transitions, parent-status auto-derivation, board progress, merge pre-flight, auto-unblock, dispatch.
- [functions.md](db-reference/functions.md) — Yoke function-call surface: envelope, registry, claim-verification matrix, and the function ids that own structured-field writes, epic-task amendment, lifecycle transitions, claim mutation, QA writes, and orchestration. The operator-readable Atlas of those surfaces lives at [docs/atlas.md](atlas.md).

## Entry points

```sh
yoke <subcommand> [args...]
yoke db read "SELECT ..."
```

Lifecycle-owned writes (item status, deploy_stage, epic_task status, the
events table) are **not** available through `query` — use the sanctioned
mutators below. The Python lint owners enforce the separation.

### Bootstrap contract

Normal runtime commands (reads, domain dispatch, structured-field writes) never trigger schema/domain bootstrap as a side effect. The module chain under `_AUTO_INIT_MODULES` runs only when:

- the operator invokes the explicit schema bootstrap subcommand; or
- the calling process sets `YOKE_DB_INIT_ALLOW=1` (test fixtures, first-run provisioning, cross-worktree DB creation).

When a normal command runs against an existing DB whose baseline schema is missing (no `items` table), the router refuses the command and prints remediation pointing at `db_router init`. No silent `CREATE TABLE` as a side effect of a read-looking command.

**Additive schema self-propagates on deploy.** Separately from the CLI bootstrap path above, the API server entrypoint (`yoke_core.api.server_entrypoint.ensure_core_schema`) runs the full idempotent `schema_init.converge_core_schema` — every `CREATE TABLE`/`CREATE INDEX` plus additive `ADD COLUMN` step — on every boot of an already-born universe. So any net-new additive table or column added to the schema-init chain reaches every born universe on its next deploy/restart with no governed migration and no manual catch-up. The governed migration runner (`migration_apply` rehearse/live-apply, with lease/audit/backup) is reserved for data-transforming changes — backfills, drops, rewrites — not net-new additive schema.

### Retired schema surface registry

Columns (and tables) retired across a project's governed migration lifecycle are catalogued in [`runtime/api/domain/retired_schema_surfaces.yaml`](../runtime/api/domain/retired_schema_surfaces.yaml). The registry is the single live source authorised to name retired columns by their literal identifier.

It feeds three downstream checks:

- The `check_implementing_to_reviewing_implementation_gate` evidence gate performs a post-state verification against the authoritative DB. If a ticket's `db_mutation_profile.affected_surfaces[].columns` names a retired column and that column is still present on the authoritative DB, the advance is blocked with remediation.
- Idempotent `ALTER TABLE ... ADD COLUMN` call sites in init/bootstrap modules consult `yoke_core.domain.retired_schema_registry.guard_add_column` before executing. A registered column skips the `ADD COLUMN` and emits a WARN `RetiredSchemaResurrectionAttempt` event.
- Doctor health check `HC-retired-schema-resurrection` (`yoke_core.engines.doctor_hc_retired_schema`) verifies each registered column is actually absent on the authoritative DB and surfaces drift as WARN.

Adding a new retirement: the governed cutover lands first (authoritative DB no longer exposes the surface, decision record authored under `docs/archive/decisions/`). Only then does the surface get an entry in the registry. Listing a surface whose column is still present is honest — doctor will surface the drift on the next run.

## Domains

| Domain | Python owner | Responsibility |
|---|---|---|
| `items` | `yoke_core.api.service_client_items` / `yoke_core.api.service_client backlog-cli` | Backlog item CRUD and structured-field writes (`spec`, `design_spec`, `technical_plan`, `worktree_plan`, `shepherd_log`, `shepherd_caveats`, `test_results`, `deploy_log`, `browser_qa_metadata`) |
| `epic` | `yoke_core.domain.epic` | Epic task management |
| `sections` | `yoke_core.domain.item_sections` | Item sections CRUD (`item_sections` table) |
| `designs` | `yoke_core.domain.designs` | Design document management |
| `shepherd` | `yoke_core.domain.shepherd` | Shepherd verdicts and dependency operations |
| `projects` | `yoke_core.domain.projects` | Projects, sites, environments, capabilities |
| `flows` | `yoke_core.domain.deployment_flows` | Deployment flow definitions |
| `runs` | `yoke_core.domain.deployment_runs` | Deployment run lifecycle |
| `envs` | `yoke_core.domain.envs` | Ephemeral environment lifecycle |
| `events` | `yoke_core.domain.events_crud` | Structured event logging and event registry |
| `qa` | `yoke_core.domain.qa` | QA requirements, runs, and artifacts |
| `release` | `yoke_core.domain.release_notes` | Release notes management |
| `ouroboros` | `yoke_core.domain.ouroboros` | Learning loop entries and wrapups |
| `query` | parameterized read-only SQL escape hatch | Raw SQL for exploratory reads — not for lifecycle mutations |
| `init` | `yoke_core.engines.schema` | Initialize DB schema |
| `help` | built-in | Print domain list or domain-specific subcommands |

Run `yoke --help` to enumerate the registered product-facing commands.

New backlog-ticket intake goes through `/yoke idea`; lower-level item
creation adapters are internal to that workflow or test/dry-run surfaces.

**Examples:**
```sh
# Item reads
yoke items get YOK-N status
yoke items list --status implementing
yoke items list --status done --fields id,title,status --limit 100

# Item writes
/yoke idea "my title"
yoke lifecycle transition YOK-N --to implementing

# Epic task operations
yoke epic-tasks list --epic 42
yoke workflow-item epic-task body-get --epic 42 --task-num 3

# Design documents
# Design artifacts are item fields or Project Structure entries; read them
# with `yoke items get` or `yoke project-structure patch apply` depending
# on the owning surface.

# Ouroboros
yoke ouroboros entry list --unreviewed

# Shepherd
yoke shepherd dependency-list YOK-N

# Structured field reads
yoke items get YOK-N spec
yoke items get YOK-N design_spec
yoke items get YOK-N technical_plan
yoke items get YOK-N browser_qa_metadata

# Structured field writes
# Each CLI adapter constructs a FunctionCallRequest internally and dispatches through the same registry.
printf '%s' "$SPEC_CONTENT" | yoke items structured-field replace YOK-N --field spec --stdin
printf '%s' "$DESIGN_CONTENT" | yoke items structured-field replace YOK-N --field design_spec --stdin
printf '%s' "$BROWSER_QA_JSON" | yoke items structured-field replace YOK-N --field browser_qa_metadata --stdin

# Item sections
yoke items section upsert YOK-N --section "Goals" --content-file /tmp/goals.md --ordering 100
yoke items section get YOK-N --section "Goals"
yoke items get YOK-N --json
yoke items section delete YOK-N --section "Goals"

# Section-preserving structured transforms
yoke items structured-field section-upsert YOK-N --section "Goals" --content-file /tmp/goals.md --ordering 100 --source operator
yoke items structured-field section-append YOK-N --section "Progress Log" --headline "Polish verification" --content-file /tmp/update.md --source operator
yoke items structured-field append-addendum YOK-N --field shepherd_caveats --heading "Polish verification" --content-file /tmp/caveat.md --source operator

# Project operations
yoke projects get --project buzz --field github_repo
yoke projects list
yoke projects create --slug myapp --name "My App" --github-repo owner/myapp   # register a new project (org admin)
yoke projects update --slug myapp --name "My App v2" --github-repo owner/myapp # edit an existing project (project admin)

# Deployment flows
# Deployment flow/run command wrappers are pending; see the Atlas before
# teaching a command-shaped recipe.

# Structured events (agent_events)
yoke events tail --limit 10
yoke events count --source-type agent --since 2026-01-01
yoke events query --event-name HarnessToolCallCompleted --agent engineer
yoke events anomalies --min-severity WARN

# Deployment runs
# Deployment run command wrappers are pending; see the Atlas before teaching a
# command-shaped recipe.

# QA requirements and runs
# Item-bound review requirement / run (full schema in db-reference/qa-cli-and-body-write.md)
yoke qa requirement add --item YOK-N --qa-kind implementation_review --qa-phase verification
yoke qa requirement list --item YOK-N
yoke qa requirement update --requirement-id 1 --field blocking_mode --value non_blocking
yoke qa run add --requirement-id 1 --executor-type agent --qa-kind implementation_review --verdict pass
yoke qa run list --requirement-id 1
yoke qa artifact add --requirement-id 1 --run-id 1 --artifact-type screenshot --artifact-handle '{"backend":"local","path":"/tmp/img.png"}'

# Epic-task review verdicts use the epic helper path
yoke workflow-item epic-task review-insert --epic 42 --task-num 3 --verdict pass --body-file <path>
yoke workflow-item epic-task review-get --epic 42 --task-num 3

# Raw diagnostic reads
yoke db read "SELECT id, title FROM items WHERE status='implementing'"
yoke db read --json "SELECT * FROM tracks"

# Source-dev/operator-debug break-glass inside a Yoke checkout
python3 -m yoke_core.cli.db_router query "SELECT 1"
```

Exit codes: 0 = success, 1 = error/not found, 2 = usage error

## Timestamp discipline

Yoke's DDL does not declare DB-level timestamp defaults. Every `created_at`, `updated_at`, `started_at`, `completed_at`, `offered_at`, `last_heartbeat`, `acquired_at`, `expires_at`, or similar column is `TEXT NOT NULL` (or `TEXT` for nullable ones) with no DB-level now-value `DEFAULT` clause (no `now()`, no `CURRENT_TIMESTAMP`). Callers supply the timestamp at INSERT time in the canonical ISO-8601 UTC format `YYYY-MM-DDTHH:MM:SSZ`.

The canonical format is sourced from `yoke_core.domain.db_helpers.iso8601_now()`:

```python
from yoke_core.domain.db_helpers import iso8601_now
conn.execute(
    "INSERT INTO ouroboros_entries (timestamp, agent, category, body, created_at) "
    "VALUES (?, ?, ?, ?, ?)",
    (ts, agent, category, body, iso8601_now()),
)
```

**Why app-supplied, not DB-level:** A DB-level now-value default (Postgres `now()` / `CURRENT_TIMESTAMP`) emits a textual form that diverges from the canonical ISO-8601 format `YYYY-MM-DDTHH:MM:SSZ` the Python layer parses via `datetime.fromisoformat(ts.replace("Z", "+00:00"))` and the GitHub-sync layer round-trips. Keeping the format in app code (one import, one call) means every INSERT call site binds the canonical timestamp explicitly, with no format-translation layer in the DB.

Native-type target (columns are `TEXT` today): timestamp columns become `TIMESTAMPTZ` with no DEFAULT; callers continue to bind `iso8601_now()`.

## Query-Time SQL Clock Helpers

Query-time time-window predicates route through `yoke_core.domain.time_sql.now_sql(...)`, which emits Postgres-native UTC timestamp text in the same ISO-8601 shape as the stored `TEXT` columns. Like `sql_json`, `time_sql` is a pure-string-emission module: callers compose the fragment into an f-string at the call site. The helper supports fixed-window offsets (`offset_days`, `offset_hours`, `offset_minutes`) and raw interval expressions (`offset_modifier`) for placeholder-driven windows, plus an optional `localtime` flag used only by the operator-facing board bucket path. For call sites that do not need SQL-evaluated "now," prefer `db_helpers.iso8601_now()` and bind the cutoff as a parameter.

## `migration_model` capability — recipe + runner vocabulary

Project-configured validation recipes and migration runners live behind
the `migration_model` `project_capabilities` row. The canonical recipe
and runner vocabulary, pairing matrix, and webapp template + Buzz seed
contract are documented at
[db-reference/migration-model-capabilities.md](db-reference/migration-model-capabilities.md).

## Live-apply provenance on `migration_audit`

`migration_apply_live` stamps accountable provenance onto every audit row it touches so an operator inspecting a completed (or failed) live-apply can reconstruct who did what against the authoritative DB without re-deriving the context. The columns are nullable so legacy rows remain readable; the writer (`yoke_core.domain.migration_apply_audit.set_audit_provenance`) silently skips on a pre-migration authoritative DB.

```sql
actor_id          TEXT  -- harness_sessions.actor_id at apply time
worktree          TEXT  -- absolute worktree_path the apply ran from
source_branch    TEXT  -- git branch in that worktree (--show-current)
source_commit    TEXT  -- git HEAD sha in that worktree
integration_target TEXT -- typically 'main'
change_class      TEXT  -- profile.migration_strategy (additive_only, hard_cutover, expand_contract)
```

The `coordination_leases.lease_id` join already linked the audit row to the lease that protected it; the new columns answer "from which checkout, by which actor, against which integration target." Doctor's `coordination-leases-unmerged-source` HC uses `source_branch` + `integration_target` to flag completed rows whose source never reached integration target — a sign the worktree was deleted before the slice merged.

## Cross-worktree migration apply (`--module-path-override`)

`yoke_core.domain.migration_apply` exposes a sanctioned cross-worktree override for the two-unit `rehearse` / `live-apply` contract. The override sources the migration module from an active feature-worktree checkout instead of the model's default `runner.config.modules_dir` so a feature ticket can apply the module it authored without staging it on `main` first. See AGENTS.md `## Governed DB Mutation` for the surrounding contract.

CLI shape (both subcommands):

```bash
python3 -m yoke_core.domain.migration_apply rehearse YOK-N \
  --module-path-override /path/under/active/worktree/<slug>.py

python3 -m yoke_core.domain.migration_apply live-apply YOK-N \
  --module-path-override /path/under/active/worktree/<slug>.py
```

Both rehearse and live-apply route through `yoke_core.domain.migration_apply_resolve.resolve_module_override` so the validation rules cannot drift between units.

**Allowed shape.** Resolved real path is a regular `.py` file under the active item worktree. The basename without `.py` (the slug) is in the item's `db_mutation_profile.migration_modules`. The migration runner passes the target worktree path to `resolve_module_override` explicitly (caller-provided); `resolve_module_override` validates the override path resolves under that worktree and does not consult any session-scope state.

**Denied shapes (each refused with `REFUSED:` and exit 4):**

- empty `--module-path-override` argument,
- caller did not pass a target worktree path (the migration runner resolves this from the item's claim before calling the helper),
- override path does not exist on disk,
- override path is a directory (or anything other than a regular file),
- override path resolves outside the active item worktree (catches symlink escape since `Path.resolve(strict=True)` follows symlinks before the relative-to check),
- basename is not `<slug>.py`,
- slug is not declared in `db_mutation_profile.migration_modules`.

`--force` does not bypass any of these. The refusal is structural so live-apply refuses rather than silently falling back to main, for both units.

**Audit/evidence (no schema migration).** When the override is in effect, the rehearsed `migration_audit` row's `description` column carries `override_source=<resolved-path>; override_worktree=<resolved-worktree>` after the canonical `two-unit apply contract (governed)` prefix. Live-apply parses the description on the latest rehearsed row via `yoke_core.domain.migration_apply_audit.assert_live_apply_override_consistent`: if the description has the marker but the live-apply caller did not pass an override (or the paths differ), the unit refuses. The same evidence appears in CLI stdout under each `rehearse` / `live-apply` summary as `override_source=... override_worktree=...`.

## JSON-payload columns

Some `TEXT` columns carry JSON payloads. These columns are `TEXT` today and become `JSONB` on the native-type cutover. The authoritative enumeration lives at `yoke_core.domain.sql_json.JSONB_COLUMNS`; this section mirrors it so doc readers have the table-level index without grepping the source.

| Table | Column | Payload shape |
|---|---|---|
| `events` | `envelope` | full event envelope JSON; readers route JSON-field reads through `yoke_core.domain.sql_json.json_get` |
| `events` | `anomaly_flags` | array payload per `docs/event-contract.md` (today a comma-separated string; migrates to JSON array on cutover) |
| `items` | `browser_qa_metadata` | validated JSON object per `yoke_core.domain.browser_qa_metadata.validate_json_string` |
| `qa_runs` | `raw_result` | JSON-encoded tool output per `docs/qa-platform.md` |
| `qa_artifacts` | `metadata` | JSON metadata envelope per `docs/qa-platform.md` |
| `deployment_flows` | `stages` | JSON array of stage objects |

These columns are annotated `-- → JSONB on Postgres` at their declaration site in the schema blocks in the topic files.

**Markdown and plain-text columns are NOT JSON payload** and stay `TEXT` on both dialects. Authoring agents occasionally conflate "long text stored in a DB column" with "JSON payload" — they are different. The following columns are markdown or plain text and must not be annotated with `→ JSONB on Postgres`:

- `items.spec`, `items.design_spec`, `items.technical_plan`, `items.worktree_plan`, `items.shepherd_log`, `items.shepherd_caveats`, `items.test_results`, `items.deploy_log` — structured markdown per the virtual-body-field model (`docs/archive/decisions/virtual-body-field.md`).
- `epic_progress_notes.body` — markdown.
- `shepherd_verdicts.caveats`, `ouroboros_entries.body`, `wrapup_reports.body` — markdown.
- `release_entries.title`, `release_entries.version`, `release_entries.category`, `release_entries.project` — plain-text identifiers.

Postgres target for markdown/plain-text columns: `TEXT` (or `VARCHAR(N)` for bounded identifiers).

## Common Pitfalls

- Function is `query_item`, NOT `_query_item`
- SQL operators: use `<>` not `!=`.
- Prefer registered `yoke ...` readers over raw SQL in shell scripts for single-item operations.
- **Structured fields:** Pipeline stages write to structured DB fields (`spec`, `shepherd_log`, `shepherd_caveats`, `design_spec`, `technical_plan`, `worktree_plan`, …) through the Yoke function-call surface: agents call function ids such as `items.structured_field.replace`, `items.structured_field.append_addendum`, `items.structured_field.section_upsert`, `items.structured_field.section_append`, `items.section.upsert`, and `items.progress_log.append`. The CLI commands (`yoke items structured-field replace`, `yoke items structured-field append-addendum`, `yoke items structured-field section-upsert`, `yoke items structured-field section-append`, and `yoke items section upsert`) build the matching `FunctionCallRequest` and dispatch through the same registry. The body is a generated view assembled by `yoke_core.domain.render_body`. Never use ad-hoc sed chains or awk on body content. Full payload shapes, claim-verification rules, and event emissions live in [db-reference/functions.md](db-reference/functions.md); the operator-readable Atlas of registered surfaces lives at [atlas.md](atlas.md).
- **Structured-field transforms (agent path):** Two operations, one envelope each. Full-field rewrites call `items.structured_field.replace` with the complete intended content. Additive transforms (preserve existing content, append a `## heading`-led block) call `items.structured_field.append_addendum` / `section_upsert` / `section_append`. The handler reads through canonical DB routing, applies an idempotent transform, writes via the existing guarded structured-write path (preserving empty/shrinkage/freeze guards), and re-reads to verify. Reading a structured field with `items get`, redirecting through a temp file or shell variable for transformation, and piping back into `items update --stdin` is blocked by `yoke_core.domain.lint_structured_field_transform_shell`. Bypass: `# lint:no-structured-transform-check` (audited).
- For bulk reads in shell scripts, use `yoke db read --json` or a registered read adapter rather than raw database clients.
- `frozen` is INTEGER in DB (0/1) but `query_item` maps it to "true"/"false"
