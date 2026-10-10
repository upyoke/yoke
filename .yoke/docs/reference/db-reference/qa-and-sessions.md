# DB Reference — QA, Release, and Session Tables

Schemas for the QA platform tables, release entries, merge locks, and harness session / claim tables. Cross-link back from [db-reference.md](../db-reference.md) for entry points, the domain catalog, timestamp discipline, JSON-payload conventions, qa CLI, body write path, and the status lifecycle reference.

## Table: qa_requirements

Stores QA requirements attached to items, epic tasks, or deployment runs. Each requirement declares what kind of QA must be performed, when in the lifecycle it is due, and what success looks like.

```sql
id INTEGER PRIMARY KEY
item_id INTEGER -- nullable; FK to items(id)
epic_id INTEGER -- nullable; FK to epic_tasks(epic_id)
task_num INTEGER -- nullable; FK to epic_tasks(task_num)
deployment_run_id TEXT -- nullable; FK -> deployment_runs(id)
deployment_stage TEXT -- nullable; pinned deployment QA stage
deployment_member_item_id INTEGER -- nullable; attached item for item-scoped stage QA
qa_kind TEXT NOT NULL -- free-form: implementation_review, simulation, smoke, e2e, visual-regression, etc.
qa_phase TEXT NOT NULL -- CHECK: verification | post_deploy | manual_acceptance
target_env TEXT -- semantic: local | preview | ephemeral | prod
blocking_mode TEXT NOT NULL DEFAULT 'blocking' -- CHECK: blocking | non_blocking
requirement_source TEXT NOT NULL DEFAULT 'explicit' -- CHECK: explicit | seeded_default | ac_derived | flow_derived
success_policy TEXT -- JSON: defines what counts as success (see below)
capability_requirements TEXT -- JSON array: e.g. ["browser","docker","ssh"]
suite_id TEXT -- nullable, unconstrained; links to future test-intelligence suite
waived_at TEXT -- ISO timestamp if waived
waiver_rationale TEXT -- why waived
created_at TEXT NOT NULL
```

**Polymorphic FK constraint:** Exactly one of (`item_id`), (`epic_id` + `task_num`), or (`deployment_run_id`) must be non-NULL. Deployment rows are legacy when stage/member are both NULL; scoped rows require a stage and use a member only for item scope. Enforced by CHECK constraint.

**Indexes:** Base subject indexes remain on item, epic task, and deployment run. Plan-case materialization uses separate partial unique indexes for legacy run, run+stage, and run+stage+member subjects. Scoped keys include the execution-target digest after plan, case key, and host baseline so a superseding receipt preserves old evidence while allowing a fresh exact-target execution.

### success_policy JSON Schema

The registered aggregate policy is all-pass:

```json
{"id":"all-pass","params":{}}
```

Each effective requirement needs a completed passing current actual attempt
with its own definition, review and subject proof. Historical passes and
attempt voting do not rescue a newer failure or pending attempt;
`qa_success_policy_invalid` names the policy correction. A method may measure
thresholds or multiple criteria inside that one attempt. Full policy and
judgment semantics live in [success-policy-schema.md](../qa-platform/success-policy-schema.md)
and [requirement-state-model.md](../qa-platform/requirement-state-model.md).

## Table: qa_runs

Records actual executions and their history. Gates select the current actual attempt before grading; multiple rows are not votes.

```sql
id INTEGER PRIMARY KEY
qa_requirement_id INTEGER NOT NULL -- FK to qa_requirements(id)
performed_by TEXT NOT NULL -- how it ran: agent, shell, playwright, manual, github-actions
qa_kind TEXT NOT NULL -- what was tested (denormalized from requirement for query convenience)
verdict TEXT -- CHECK: pass | fail | undetermined | error (nullable until inspection writes it)
verdict_reason TEXT -- required when undetermined; agent outcomes also require linked evidence
execution_status TEXT -- CHECK: captured | capture_failed (nullable for non-browser runs)
score REAL -- nullable numeric score
confidence REAL -- nullable confidence level (0.0-1.0)
raw_result TEXT -- → JSONB on Postgres; JSON: full execution output
duration_ms INTEGER -- nullable execution duration
started_at TEXT -- ISO timestamp
completed_at TEXT -- ISO timestamp
created_at TEXT NOT NULL
```

**Index:** `idx_qa_runs_requirement(qa_requirement_id)`

**Capture vs inspection.** For requirements whose `method_id` is
`browser-check` or `browser-inspection`, the two columns serve distinct
concerns:
- `execution_status='captured'` means the daemon successfully saved the expected screenshots to disk.
- `execution_status='capture_failed'` means the daemon errored, an artifact path was missing, a step failed, or completeness check failed.
- `verdict` is set **only after screenshot inspection** (LLM or human evaluation of the screenshot content). Infrastructure success alone never writes `verdict='pass'`.
- Typical lifecycle: `yoke qa case run --requirement-id <id>` records the
  method's execution result. An evidence-backed Browser inspection can remain
  undetermined, halting the item until a project owner/operator resolves its
  `qa_needs_review` request. Missing evidence is an execution failure and asks no human.

Every downstream gate that filters `verdict='pass'` (status-transition, pre-merge, pre-deploy, flow-gate updates) therefore gates on inspection outcome, not capture.

**Evidence currency:** a pass must answer for the exact code and frozen
target the gate evaluates. Commit-time ordering or an unavailable branch is
not identity proof. The [case attachment contract](../qa-platform/case-attachment.md)
owns immutable target binding, receipt supersession and candidate checkout;
the [QA platform](../qa-platform.md) owns current gate and evidence rules.
Stale or out-of-scope evidence retains its history and names the rerun or
rebind recovery rather than satisfying a different candidate.

## Table: qa_artifacts

Links binary/text artifacts (screenshots, diffs, logs, traces) to a QA run.

```sql
id INTEGER PRIMARY KEY
qa_run_id INTEGER NOT NULL -- FK to qa_runs(id)
artifact_type TEXT NOT NULL -- screenshot, diff_image, log, trace, etc.
content_type TEXT -- MIME type: image/png, text/plain, etc.
artifact_handle TEXT -- typed handle JSON: {"backend":"s3","bucket":B,"key":K} or {"backend":"local","path":P}
metadata TEXT -- → JSONB on Postgres; JSON: dimensions, file size, etc.
created_at TEXT NOT NULL
```

**Index:** `idx_qa_artifacts_run(qa_run_id)`

**Artifact handles:** `artifact_handle` is the only file reference — a typed
JSON document naming where bytes live. All submitted files and inline bytes use
the configured project S3 store; upload completes before its row is recorded.
Only a genuinely unconfigured bucket selects permanent server-local storage;
hosted tenants use `YOKE_QA_ARTIFACT_BROKER_URL`, `YOKE_QA_ARTIFACT_BROKER_TOKEN_FILE`,
`YOKE_QA_ARTIFACT_BUCKET`, and immutable `YOKE_QA_ARTIFACT_PREFIX` settings.
Invalid configured storage returns its real error without a row or local
downgrade. Existing readable local handles and repo baselines remain supported,
but bare paths are refused. Gates check local files and accept valid S3 handles
structurally without an added network call.


## Table: release_entries

```sql
id INTEGER PRIMARY KEY
item_id INTEGER NOT NULL -- backlog item ID
category TEXT NOT NULL DEFAULT 'improvements' -- features|improvements|bug_fixes|internal
title TEXT NOT NULL
version TEXT NOT NULL
project_id INTEGER NOT NULL REFERENCES projects(id) -- explicit attribution
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
UNIQUE(item_id, version, project_id)
CHECK(category IN ('features','improvements','bug_fixes','internal'))
```

## Table: merge_locks

```sql
id INTEGER PRIMARY KEY
session_id TEXT NOT NULL
branch TEXT NOT NULL
epic_id TEXT
acquired_at TEXT NOT NULL
expires_at TEXT NOT NULL
```

## Table: harness_sessions

Tracks active harness sessions and their registered identity. Sessions with `ended_at IS NULL` are active. A persisted active work claim protects its live holder regardless of heartbeat age, park mode, process presence, or relay restart. The scheduler reports that claim as `claimed_by_other_live`; stale-session reclaim refuse to release it with `reason=active_work_claim`. Explicit release, completion, cancellation, or authorized termination settles ownership. Parking records a delivery wait for wake routing but does not decide retention. Derived liveness (`sessions.list`, `yoke_core.domain.session_staleness.session_liveness`) is `active`, `waiting`, `stale`, or `ended`: a parked live session holding an active work claim is `waiting`, never `stale`. Wake and message routing key on the activity-only `activity_liveness` instead. Each roster row also carries `reclaimable`, the same `stale_reclaim_candidate` predicate `find_stale_sessions` applies, so the Sessions page counts only sessions the sweep would act on.

**Stale-session thresholds (canonical reference).** The reclaim windows are config-tunable, not code literals. The sweep first selects an occupancy tier:

- `session_stale_ttl_minutes` (default `20`) — the short tier for a session with no active work claim, no session-owned strategy-document claim, and no session-owned coordination lease. One base applies on every harness; transient stop signals attempt only a non-destructive empty-session end.
- `session_stale_ttl_with_holdings_minutes` (default `1440`) — the minimum tier for session-owned strategy-document locks. Active work claims have no inactivity bound. `yoke sessions terminate SESSION-ID --reason R` requires a live steering seat covering the target project to release a stranded holder; acquire it with `yoke claims steering acquire --project P --reason TEXT` or route via `yoke say --steering`. It refuses a session a wake is resuming as `TERMINATION_RESUME_IN_FLIGHT` — a `wake_relay` attempt started at or after the recorded native exit that is still open or resumed a process not yet reported exited, within the resume-custody quiet window — because a headless worker's process exits between turns and a message resumes it; `--allow-resume-in-flight` overrides for a deliberate restaff or evidence it cannot resume. Logical stop and physical exit are separate: one bounded TERM/KILL attempt (2-second TERM grace, then up to 2 seconds to verify exit; Claude job-stop command timeout 20 seconds) retains custody on missing/denied/unverified results. Inspect custody and permissions, then repeat the explicit termination command to retry a failed physical reap; pending and verified successful requests are idempotent, with prior failed evidence retained in the existing reap row.
Resolver: `yoke_core.domain.sessions_analytics_core` owns both source thresholds. The sessions-card stale-eligible time is absent while an active work claim protects its holder.

**Long commands and sparse tool boundaries.** Registered Command cases and watcher-backed suites refresh the owning session and claims while the child runs. The persisted work claim protects a silent or crashed holder until explicit release or terminal action.

```sql
session_id TEXT PRIMARY KEY -- globally unique session ID (from contract)
executor TEXT NOT NULL -- executor identity (e.g., claude-code, codex)
provider TEXT NOT NULL -- model provider (e.g., anthropic, openai)
model TEXT -- provider-attested served model; NULL until attested and landed
reasoning_effort TEXT -- served effort, distinct from requested_reasoning_effort
context_window_tokens INTEGER -- served window, distinct from requested_context_window_tokens
usage_totals TEXT -- measured usage document; parse through session_usage_facts
execution_level TEXT NOT NULL DEFAULT 'primary' -- session grouping identity stamped by session-routing settings
capabilities TEXT DEFAULT '[]' -- JSON array of capability tags
workspace TEXT NOT NULL -- absolute path to working directory
mode TEXT DEFAULT 'wait' -- session mode (charge, feed, strategize, wait); scheduling posture only, never authority
offered_at TEXT NOT NULL -- ISO 8601 when session was registered
last_heartbeat TEXT NOT NULL -- ISO 8601 of last heartbeat
native_process_gone_at TEXT -- when the death was first seen, not when last reported
native_process_gone_evidence TEXT -- bounded JSON evidence from local records
ended_at TEXT -- NULL while active; set when session ends
offer_envelope TEXT -- checkpoint and skip-memory telemetry JSON (optional)
actor_id INTEGER -- registered acting identity; legacy/additive storage permits NULL
```

**Actor binding.** A session a person opened binds that person's identity. A session another session LAUNCHED binds the launching actor, transitively — the launch's `requester_actor_id`, read at registration through the authenticated launch side channel, outranks both the machine's OS login and a relay's bearer-token actor, and an unreadable launch refuses registration rather than falling back to either. Every action one session takes on another (message, wake, keep-alive, terminate, launch) writes a `SessionActionPerformed` row into the TARGET session's history carrying the ACTING actor, and is role-checked against the target project by `yoke_core.domain.session_action_authority`: project membership for messaging, waking, holding alive, and terminating a launched worker; project owner or org admin for terminating another actor's interactive session. Contract: `docs/archive/decisions/session-actor-follows-the-person.md`.

The process-gone columns record machine evidence without ending a claim holder. The reporting machine keeps its record until the control plane ends the session, so a retained session is reported again every poll; the stamp is the native's own exit time where the machine read one (correcting an earlier report's guess), else the time this session's first report about that same process earned, and a report about a different, older process is dropped whole rather than overwriting newer evidence, so later activity can still supersede it. `sessions.list.native_process` exposes the observation until a later heartbeat, tool call, or episode start supersedes it, and drops it when the evidence measured `exit_code` 0 under a session that declared a wait — parked, turn_posture waiting whose `turn_posture_at` is present and not before the current `episode_started_at`, or holding an item armed in the merge queue — because a finished headless command is that wait rather than a disappearance; a non-zero exit and an exit nobody measured still read as gone. The `offer_envelope` column retains checkpoint and skip-memory telemetry.

**Chain checkpoint:** The checkpoint API persists handler outcome and work identity for recovery and telemetry. Terminal closeout consumes a matching checkpoint. Checkpoint budget does not block session ending; idle cleanup preserves active claims, document locks, keepalive holds, and pending launch or wake delivery. Read through `yoke sessions checkpoint-read`.

**Probe sessions are audit rows.** A probe has ended within `PROBE_MAX_LIFETIME_SECONDS` (30) of `offered_at`, has `tool_call_count = 0`, and has no `first_user_prompt_at` stamp. The stamp is written on the session row at the prompt boundary. Probe rows remain in `harness_sessions` for audit; operator-facing session lists and steering counts exclude them through the shared `session_probe` predicate. Live sessions are never classified as probes.

Indexes: `idx_harness_sessions_level(execution_level)`, `idx_harness_sessions_heartbeat(last_heartbeat)`.

Shell access: the Python harness-session CLI (`begin|touch|end|get|list|stale|reclaim`). API: `/v1/sessions` endpoints.

## Table: work_claims

Tracks active harness-session occupancy through one canonical target pair: `target_kind` names the target vocabulary and `scope` stores the exact kind-specific JSON object. Claims with `released_at IS NULL` are active.

- **Item** (`target_kind='item'`): `scope={"item_id":N}`.
- **Epic task** (`target_kind='epic_task'`): `scope={"epic_id":N,"task_num":N}`.
- **Process** (`target_kind='process'`): `scope={"process_key":K,"conflict_group":G}`. STRATEGIZE and FEED share `strategy-control-plane:<project>` and therefore conflict.
- **Steering** (`target_kind='steering'`): `scope={"project_id":N}` or `{"project_id":N,"document":SLUG}`; N identifies the document's owning project for a document seat. Distinct non-overlapping document seats may coexist. Paired locks remain in `strategy_doc_claims` through `steering_claim_id`.

Domain validation requires each kind's keys and permits steering's optional document key. Storage has no specialized target, typed-owner, or registration-provenance columns.

```sql
id INTEGER PRIMARY KEY
session_id TEXT NOT NULL -- FK to harness_sessions.session_id
target_kind TEXT NOT NULL -- item|epic_task|process|steering|migration_serialization|qa_admission|route_qualification (deploy_serialization: retained history only)
scope TEXT NOT NULL -- canonical JSON object; exact shape is validated by target_kind
claim_type TEXT NOT NULL DEFAULT 'exclusive' CHECK(claim_type='exclusive')
claimed_at TEXT NOT NULL
last_heartbeat TEXT NOT NULL
released_at TEXT
release_reason TEXT -- completed, released, reclaimed, handed_off, expired, session_ended
reason TEXT -- verbatim acquisition rationale
reason_intent TEXT -- canonical acquisition intent
release_reason_intent TEXT -- caller's release intent
```

Indexes: `idx_work_claims_session(session_id)`, `idx_work_claims_session_released(session_id, released_at)`, and `idx_work_claims_heartbeat(last_heartbeat)`.

Active-claim exclusivity invariants — these partial unique indexes, each scoped to `released_at IS NULL` so historical released overlap rows remain queryable evidence:

- `idx_work_claims_active_item ON work_claims(scope) WHERE released_at IS NULL AND target_kind='item'`.
- `idx_work_claims_active_epic_task ON work_claims(scope) WHERE released_at IS NULL AND target_kind='epic_task'`.
- `idx_work_claims_active_process_conflict` indexes `scope.conflict_group` where the process claim is active.
- `idx_work_claims_active_steering ON work_claims(scope) WHERE released_at IS NULL AND target_kind='steering'`.

The item and epic-task indexes are the authoritative storage-level prevention layer for concurrent writers from separate database connections; the application-level `WHERE NOT EXISTS` check inside `claim_work` remains in place for readable holder lookups, but the partial unique indexes are what guarantee two writers cannot both leave unreleased active rows for the same work unit. A losing concurrent writer surfaces as `SessionError("ALREADY_CLAIMED")` with the winning session id preserved in the message.

A steering seat covers a scope, not a project. Its `scope` is `{"project_id": N}` for a whole project, or `{"project_id": N, "document": "SLUG"}` for one strategy document owned by that project. Two seats coexist unless their scopes overlap: two documents in one project are two seats, while a project seat overlaps only CURRENT-PLAN document steering of that project. A refusal names the holder's actor, machine, and session, and points at both `yoke claims steering list --project P --active-only` and taking a seat on a different document. Steering is therefore the one kind whose exclusivity is not an index — two overlapping scopes are different JSON objects, so no unique index on `scope` can reject the pair. Its storage-level layer is the `SELECT ... FOR UPDATE` on the project row that `acquire` takes before it evaluates overlap, which serializes every steering acquire in one project; the index on `scope` remains as the narrower guarantee that one exact scope has one live row. A project seat covers its unlinked items and CURRENT-PLAN members, excluding other document-linked items even without a live document seat; a document seat covers items linked to that exact owning-project/document identity in `item_strategy_docs`, including items executing in other projects — the link `strategy.execution.link` writes, and the one `items.create` writes when intake names a `strategy_doc`. Membership is read live, so a link written after a message was sent still decides which seat the message is now the business of. The fleet report for a document seat lists only its items; delivery-plane and machine facts (unregistered launches, launchable surfaces, plan limits) stay project-wide because a launch with no bound session has no item to attribute and machines are shared by every seat on them. Steering acquisition locks the project row, then creates the seat and, for a document seat, that document's lock in one transaction. A document conflict rolls back the seat. A project-wide seat may lock a standing plan with `--plan-doc`; without that flag it locks no document. Releasing one seat releases only its paired document lock, even when the session holds another seat in the same project. Steering release and stale-session reclamation release each pair together, while direct release of the paired document is refused until the seat leaves.

Shell access: item/process targets use `yoke claims work`; steering uses `yoke claims steering acquire --project P [--doc SLUG | --plan-doc SLUG] [--reason TEXT]` (`--doc` narrows the seat to that document's linked items; `--plan-doc` locks the standing plan while the seat covers the whole project; neither flag covers the project and locks nothing), `list [--project P] [--active-only]` (which names each seat's scope, holder actor, and machine), and `release CLAIM_ID --reason TEXT`. All dispatch through `/v1/functions/call`. `claims.steering.list` answers for one project, so a caller asking which seats exist across every project it can see reads `sessions.steering_groups.list` (`yoke sessions steering-groups list`): no inputs, one row per live seat, carrying the seat's session id under the same `steering_group_session_id` name the session roster spells it on every row that seat covers. Visibility is deliberately the OR the roster applies, because a session steers a project it did not start in — a seat is visible when the project it steers is visible, or when the session holding it lives in a visible project. `yoke_core.domain.sessions_steering_groups_read.live_steering_group_session_ids` is the read, over the same `steering_scope_coverage.live_steering_claims` rule the roster's own projection uses, so a released claim and an ended holder are seats in neither. Its one consumer today is the app's card tint, which ranks groups by sorted seat id and reads nothing else; reaching that through the roster cost a second complete roster per mount — claims, holdings, delivery, presentation — for one repeated field.

### Steering fleet report

What a steering session cannot see from inside its own turn: available work, quiet claim holders, and four failures that arrive as silence, composed server-side and appended to the messages that session already receives. See [steering-fleet-report.md](steering-fleet-report.md).

### Live claim-holder lookup

The canonical recipe for "which session currently holds the work claim on `PREFIX-N`?" is the registered read (function id `claims.work.holder_get`):

```sh
yoke claims work holder-get PREFIX-N
```

It returns the active `work_claims` row (`released_at IS NULL`) — `claim_id`, holder `session_id`, `target_kind`, `scope`, `claimed_at`, and `last_heartbeat` — in one call. Item lookup matches `target_kind='item'` plus canonical `scope={"item_id":N}`; do not query removed specialized or owner columns. The same recipe is the canonical example in the generated agent context packet (`yoke_core.domain.schema_api_context`, topic `claims`).

Inside the Yoke source repo only, the in-tree `python3 -m yoke_core.hooks.sessions_cli who-claims <item-id>` helper additionally joins the owning `harness_sessions` row (surfacing `executor` and `mode`) and accepts `--current-episode`. That module is not importable from an installed Yoke, so it is an operator/debug recipe for this repo, never a portable one.

`work_claims` is the **active session occupancy** primitive — including which session currently steers a project or strategy-doc scope. It is NOT path/file ownership truth (that lives in `path_claims`) and NOT a dangerous shared-operation lock (that is the sticky coordination kinds below). Process path claims attribute back to their owning process work-claim through `path_claims.owner_work_claim_id`.

## Shared-operation coordination claims

Three `work_claims` target kinds coordinate a resource that is not a unit
of backlog work. They live in the same table as every other claim, so one
system carries session binding, heartbeat, telemetry, and the board's
Claims column for every hold.

| target_kind | scope | Coordinates |
|---|---|---|
| `migration_serialization` | `{"project_id":N,"model":M,"item_id":N}` | Migration territory for one model, owned by the authoring item |
| `qa_admission` | `{"machine_id":ID}` | One physical test machine, globally |
| `route_qualification` | `{"project_id":N,"grant_key":K}` | One private-route qualification grant |

Each has a unique partial index over its exclusivity unit, so a second
holder is refused at the database rather than by a read-then-write race.
`migration_serialization` conflicts on `(project_id, model)` — the
`item_id` in scope records who owns the hold, not what is held, which is
what lets the same item re-enter and heartbeat while any other lane is
refused. `qa_admission` has no project in scope on
purpose: a physical machine is one resource whichever project drives the
run.

**Stickiness is the property that separates these kinds from the rest.**
`migration_serialization` and `qa_admission` are sticky: the
stale-session sweep, the session-end release, and the claim-free end
check all skip them, because the migration and the remote suite keep
running after the session that started them goes quiet. Recovery is the audited human operator release,
never an automatic reclaim. `route_qualification` is liveness-bound like
the backlog kinds — a grant is only valid while its steering session
lives — so the sweep reclaims it normally.

Each claim is addressed by one operator key: `LIVE_DB_MIGRATION:<model>`,
`QA_HOST:<machine>`, and the qualification grant token. QA_HOST keys are machine-scoped: list with `yoke coordination-claim list --key QA_HOST:<machine> --active-only --json`, ignoring any project filter. Signed-in humans outside harness sessions recover a reviewed row with `yoke coordination-claim release --key QA_HOST:<machine> --claim-id N --holder-session-id S --reason R`; permission remains the holder's project `claims.release`. Other key kinds still require `--project P` for operator release. QA host holders can release by claim id with `yoke claims work release --claim-id N --reason TEXT` after run completion; requirement reads and artifact uploads retain the stored member's project authority after membership ends.

Deployment runs take no coordination claim. `deploy_serialization` rows
are the retained history of the retired per-project deploy lock: nothing
takes one, a `DEPLOY:` key refuses with `deploy_lock_retired`, and runs
serialize by the servers they occupy, described in
[`deployment-run-records.md`](deployment-run-records.md).

### BOARD.md Claims column rendering

The Active Harness Sessions and Recent Sessions tables share one Claims column that renders all three primitives as keycap entries. The shapes:

| Primitive               | Active shape                | Example                            |
|---                      |---                          |---                                 |
| work_claim (item)       | `PREFIX-N`                     | `PREFIX-N`                         |
| work_claim (epic task)  | `PREFIX-N T###`                | `PREFIX-N T008`                    |
| work_claim (process)    | `⚙ <process_key>`           | `⚙ FEED`                           |
| work_claim (steering)   | `🛞 steering <project> · <documents>` | `🛞 steering yoke · CURRENT-PLAN` (a project seat holds no document and renders `🛞 steering yoke`) |
| work_claim (other kind) | `<kind>:<compact-scope>`    | `future_kind:{"k":"v"}`            |
| uncovered strategy_doc_claim | `🛞 <project> · <document>` | `🛞 yoke · MISSION`              |
| work_claim + same-item path_claim decoration | `PREFIX-N 📁<total>`           | `PREFIX-N 📁23`                    |
| path_claim orphan       | `📁<total> (PREFIX-N)`         | `📁5 (PREFIX-N)`                   |
| path_claim process anchor | `📁<total> (⚙ process_key)` | `📁3 (⚙ FEED)`                     |
| coordination claim      | `🔒 <key>`                  | `🔒 QA_HOST:mac-mini-lab` |
| coordination claim (item-owned) | `🔒 <key> (PREFIX-N)` | `🔒 LIVE_DB_MIGRATION:primary (PREFIX-N)` |

Rules: same-session multiple `path_claims` on the same item roll up into one keycap with the summed declared-path total; coordination claims never decorate work_claims (they stay `🔒` keycaps and are omitted from the work-claim list so they do not also render as `?`); ordering inside a row is work_claims → uncovered document locks → orphan path_claim keycaps → coordination claims. A steering seat folds in document locks from the same project: current seats name current locks, while released seats name released locks whose hold windows overlapped. Project id is part of the lock key, so same-named documents in two projects remain separate rows; a lock with no matching seat keeps its own keycap. A seat without a lock renders `no doc lock`. During a server/client rollout, an older recorded board payload without the pairing read keeps the seat and lock as separate rows instead of failing the render. Repeat work claims on the same rendered target and repeat coordination claims on the same key each collapse to the most recent row (one keycap). Steering occupancy is this column, not a separate Steering section. Release reasons are not rendered on Claims — drill into claim detail surfaces for audit history. Released path_claims and coordination claims do not appear on active-session rows. Per-file enumeration is intentionally out of scope — operators drill into per-file detail via `path-claims list --item PREFIX-N`.

### Scheduling and registered identity
`compute_schedule()` serves charge, steering, board, fleet and frontier. Explicit staffing follows pinned workflow bindings. Registration separates requested facts from provider-attested served model/effort/window facts; missing served values remain unattested.
Window sources are declared by `yoke_contracts.session_context_window_sources`: Codex rollout `turn_context.model_context_window`; Claude status-line JSON `context_window.context_window_size`; Cursor none. Cursor's store names only `modelName`, display labels spell a window, and `cli-config.json` context is a request. Claude's rendered `statusLine` records the window for the next hook and displays model/window/usage; Claude permits one status line and hides most footer keyboard hints when configured. An override in `.claude/settings.local.json` replaces it and gives up this attestation, leaving the window NULL. Claude alone records its window separately from its model, so its cheap window read continues after expensive model reads settle. Settlement requires a served-model hook COMPLETED against the control plane: failed-open/timed-out relays retry. NULL model means unattested or not landed.
`usage_totals` records measured consumption from `yoke_contracts.session_usage_sources`: Claude assistant `message.usage` (cache writes split by lifetime, thinking within output), Codex cumulative `token_count` (input includes cached input, output includes reasoning), Cursor optional parent-turn `stop` fields or print-mode result `usage`; absent fields mean unavailable for that surface. Readers normalize disjoint billable buckets `input`, `cached_input`, `cache_write`, `cache_write_long`, `output`. `reasoning` is a labelled subset of output, never added again. `cost_caveat` describes pricing uncertainty (multiple served models or unreadable model history), separately from measured token completeness. Parse stored documents through `yoke_contracts.session_usage_facts.usage_from_document`.
Readers are incremental, bounded and idempotent. A per-session watermark under machine Yoke home folds only new artifact bytes; relay sends absolute totals and the control plane replaces them, so duplicate delivery cannot inflate usage. Fixed-size streaming retains accumulators, not whole artifacts. Oversized records are streamed for declared relevant scalars; finish a record crossing the scan-byte bound before stopping so the next offset never skips its statement. An unreadable relevant statement marks `partial` with reason; irrelevant large records cost no completeness; stopping short merely says resume. Reader versions trigger one re-fold when recovery improves: accumulating readers restart from zero/empty totals, replacement readers use held totals. Codex's resumable fold also carries model/effort/window; Claude's model read uses a bounded transcript tail.

Only the newest served statement may attest a fact. A fold behind the artifact end attests nothing historical and reopens hook resolution until caught up; settling otherwise stops model scans. Persist checkpoints atomically and serialize folds per session/reader, avoiding offset-zero replay or an older offset overwriting a newer one. Mid-fold hooks use persisted totals. Claude deduplicates repeated response usage by message id. Rotation/truncation rereads from start and marks partial with earlier history gone. A reading measuring nothing never replaces a measured one; no token source means unavailable with reason, never fabricated zero.

Cursor print-mode result arrives after the last hook. The starting machine folds its native's settled capture, never a half-written JSON object, deduplicates `request_id`, and relays through `session_control.relay.liveness` with the same never-unlearn rule even if an active claim keeps the session alive. Attribution follows machine custody of the launched native, not identity printed in the result.

Dollar cost is derived, never stored: `yoke_contracts.session_usage_pricing` uses the immutable catalog revision effective at initial `offered_at`, including after reactivation. Unknown model/unpriced bucket yields named partial/unavailable cost; an estimated rate remains labelled estimated. Price gaps never block raw capture. Every displayed number is an **API-equivalent estimate**; subscription meters have no published dollar conversion. Roster clients use derived `usage_tokens`, `usage_status`, `usage_cost_usd`, `usage_cost_status`, `usage_note`.

**Machine-card 24-hour usage window.** `sessions.list` with `usage_last_24h: true` is mutually exclusive with every other filter and returns unpaginated authorized rows (`actor_visible_project_ids`) with session/machine ids and derived usage fields. Cohort: sessions ended in trailing 24 hours UNION sessions started (`offered_at`) inside it and still open. These disjoint halves count each session once; older still-open sessions are excluded because cumulative totals do not measure only this window. `sessions_history_read.read_recent_session_usage_by_machine` dates ended sessions through `ended_at_sql` (fallback `terminated_at`), excludes probes through shared `not_probe_session_sql`, and excludes missing `machine_id`. `appendMachineUsage` in `universe_machines_usage.js` sums per machine; labels `24H TOKENS`, `24H API COST`, `24H SESSIONS` carry the window. Fetch once per machines-panel load/redraw, independently of roster filters.
