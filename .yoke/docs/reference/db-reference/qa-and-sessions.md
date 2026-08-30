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

**Polymorphic FK constraint:** Exactly one of (`item_id`), (`epic_id` + `task_num`), or (`deployment_run_id`) must be non-NULL. Enforced by CHECK constraint (same pattern as `reviews`).

**Indexes:** `idx_qa_requirements_item(item_id)`, `idx_qa_requirements_epic(epic_id, task_num)`, `idx_qa_requirements_deployment(deployment_run_id)`

### success_policy JSON Schema

The `success_policy` column stores a JSON object defining what counts as success. It must support non-binary, statistical, and composite assessments. Examples:

```json
// Deterministic
{"type": "deterministic", "check": "exit_code", "expected": 0}

// Threshold
{"type": "threshold", "metric": "score", "min": 3.5, "max": 5.0}

// Statistical
{"type": "statistical", "required_passes": 7, "total_runs": 10}

// Agent judgment with confidence
{"type": "agent_judgment", "min_confidence": 0.8, "pass_threshold": 0.8, "fail_threshold": 0.4}

// Composite (multi-criteria)
{"type": "composite", "criteria": [
 {"metric": "layout_score", "min": 4},
 {"check": "no_missing_elements"},
 {"metric": "color_match", "min_pct": 80}
]}
```

Downstream consumers (conduct, usher) implement policy evaluation. A centralized evaluation engine is deferred. Full per-type semantics live in [qa-platform/success-policy-schema.md](../qa-platform/success-policy-schema.md).

## Table: qa_runs

Records individual QA executions against a requirement. Multiple runs per requirement support statistical success policies.

```sql
id INTEGER PRIMARY KEY
qa_requirement_id INTEGER NOT NULL -- FK to qa_requirements(id)
performed_by TEXT NOT NULL -- how it ran: agent, shell, playwright, manual, github-actions, remote-browser
qa_kind TEXT NOT NULL -- what was tested (denormalized from requirement for query convenience)
verdict TEXT -- CHECK: pass | fail | undetermined | error (nullable until inspection writes it)
verdict_reason TEXT -- required when verdict is undetermined
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
  method's execution result. Browser inspection cases remain undetermined
  until their review request is approved, rejected, or waived.

Every downstream gate that filters `verdict='pass'` (status-transition, pre-merge, pre-deploy, flow-gate updates) therefore gates on inspection outcome, not capture.

**Browser run freshness:** For Browser method cases, the QA gate checks that
passing runs are **fresh** — i.e., their `created_at` is at or after the
latest commit timestamp on the item's branch. If an Engineer retry changes
code after a Browser case was recorded, the prior passing run is stale and
does not satisfy the gate. This prevents evidence for a different deployed
revision from passing. The freshness check applies only to rows that already
carry `verdict='pass'`; unresolved inspection rows fail the verdict predicate
first. When no branch can be resolved (for example, an item without a
worktree), the freshness check is skipped gracefully.

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
JSON document naming where the bytes live. `s3` handles are durable evidence
uploaded at record time (the orchestrator mints a presigned PUT via
`qa.artifact.presign`, uploads, then records); `local` handles explicitly
declare machine-local evidence (tests, manual fallbacks, repo-committed
baselines). Bare paths are refused by `qa.artifact.add`. Gates verify `local`
handles on disk and accept well-formed `s3` handles structurally (the upload
preceded the record; lifecycle gates add no network calls).


## Table: release_entries

```sql
id INTEGER PRIMARY KEY
item_id INTEGER NOT NULL -- backlog item ID
category TEXT NOT NULL DEFAULT 'improvements' -- features|improvements|bug_fixes|internal
title TEXT NOT NULL
version TEXT NOT NULL
project TEXT NOT NULL DEFAULT 'yoke' -- project scope
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
UNIQUE(item_id, version, project)
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

Tracks active harness sessions offering themselves to Yoke for work assignment. Identity fields align with the session-offer contract. Sessions with `ended_at IS NULL` are considered active. The stale-session sweep uses activity recency plus the session's active holdings to select its reclaim threshold.

**Stale-session thresholds (canonical reference).** The reclaim windows are config-tunable, not code literals. The sweep first selects an occupancy tier:

- `session_stale_ttl_minutes` (default `20`) — the short tier for a session with no active work claim, no session-owned strategy-document claim, and no session-owned coordination lease. One base applies on every harness: fleet machinery ends sessions at every stop, so silence means the same thing everywhere.
- `session_stale_ttl_with_holdings_minutes` (default `1440`) — the minimum tier for a session holding any of those three active resources. It prevents a long foreground command from losing its claim or lock merely because no tool-boundary heartbeat landed.

Resolver: `yoke_core.domain.sessions_analytics_core` owns both source thresholds, `yoke_core.domain.session_cleanup_holdings.effective_cleanup_ttl` selects `max(short, holdings)` when the session has active holdings, and the sessions-card stale-eligible badge reads that same effective TTL. Downstream documentation should cite the config keys above by name rather than the current literal values — values may shift; the key names are stable.

**Long commands and sparse tool boundaries.** Registered Command cases and watcher-backed suites run through `yoke_core.tools._watch_runner.run_watcher`, which refreshes the owning session and active claims while the child runs. A generic foreground command may not pass through that watcher or reach another tool boundary before the short TTL. The holdings tier is the sweep-side safety net for that silent interval; a crashed holder still becomes reclaimable after the longer configured window.

```sql
session_id TEXT PRIMARY KEY -- globally unique session ID (from contract)
executor TEXT NOT NULL -- executor identity (e.g., claude-code, codex)
provider TEXT NOT NULL -- model provider (e.g., anthropic, openai)
model TEXT NOT NULL -- model identifier (e.g., claude-opus-4-7)
execution_lane TEXT NOT NULL DEFAULT 'primary' -- lane identity; path eligibility comes from lane_paths_<lane> config
capabilities TEXT DEFAULT '[]' -- JSON array of capability tags
workspace TEXT NOT NULL -- absolute path to working directory
mode TEXT DEFAULT 'wait' -- session mode (charge, feed, strategize, wait)
offered_at TEXT NOT NULL -- ISO 8601 when session was registered
last_heartbeat TEXT NOT NULL -- ISO 8601 of last heartbeat
ended_at TEXT -- NULL while active; set when session ends
offer_envelope TEXT -- full offer envelope JSON (optional; includes supported_paths, max_chain_steps, chain_checkpoint)
```

The `offer_envelope` column stores the full session-offer JSON including `supported_paths` (list of canonical downstream path names the session can execute), `max_chain_steps`, and the persisted `chain_checkpoint`. When `supported_paths` is non-empty, the decision engine validates the required path against it and returns `escalate` with `escalate_reason: "unsupported_path"` if the path is not supported. See `.yoke/docs/reference/session-offer.md` for the path derivation mapping.

**Chain checkpoint:** After each `/yoke do` mode handler returns, a `chain_checkpoint` key is written into `offer_envelope` via `update_chain_checkpoint()`. This persists the post-handler state (`step`, `action`, `chainable`, `handler_outcome`, `item_id`, `task_num`, `status`, `required_path`, `completed_at`) so that Step C of the loop can consult durable state rather than prompt-local variables when deciding whether to re-offer. The same envelope's `max_chain_steps` value lets normal `session-end` reject premature cleanup with `CHAIN_PENDING`; `--force` / `force=true` does not bypass that guard. The explicit chain-end override flag plus a non-empty rationale is required and emits `ChainDeclineOverridden`. Sessions holding unreleased claims stay active until the claim lifecycle releases them, the stale-session cleaner (`yoke sessions reclaim-stale --confirm`) reclaims them, or a human explicitly uses `python3 -m yoke_core.api.service_client claim-release`. Read via `read_chain_checkpoint()` or the `session-checkpoint-read` CLI command.

Indexes: `idx_harness_sessions_lane(execution_lane)`, `idx_harness_sessions_heartbeat(last_heartbeat)`.

Shell access: the Python harness-session CLI (`begin|touch|end|get|list|stale|reclaim`). API: `/v1/sessions` endpoints.

## Table: work_claims

Tracks active harness-session occupancy through one canonical target pair: `target_kind` names the target vocabulary and `scope` stores the exact kind-specific JSON object. Claims with `released_at IS NULL` are active.

- **Item** (`target_kind='item'`): `scope={"item_id":N}`.
- **Epic task** (`target_kind='epic_task'`): `scope={"epic_id":N,"task_num":N}`.
- **Process** (`target_kind='process'`): `scope={"process_key":K,"conflict_group":G}`. STRATEGIZE and FEED share `strategy-control-plane:<project>` and therefore conflict.
- **Steering** (`target_kind='steering'`): `scope={"project_id":N}`. There is one live session-owned steering seat per project. Its document lock remains in `strategy_doc_claims`, linked by `paired_work_claim_id`; work-claim scope stays project-only.

Domain validation requires exactly the keys for the named kind. Storage has no specialized target, typed-owner, or registration-provenance columns.

```sql
id INTEGER PRIMARY KEY
session_id TEXT NOT NULL -- FK to harness_sessions.session_id
target_kind TEXT NOT NULL CHECK(target_kind IN ('item','epic_task','process','steering'))
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

Steering acquisition locks the project row, then creates the project seat and selected document lock in one transaction. `CURRENT-PLAN` is the default; `--doc SLUG` selects another document. A document conflict rolls back the seat. Steering release and stale-session reclamation release the pair together, while direct release of the paired document is refused until the seat leaves.

Shell access: item/process targets use `yoke claims work`; steering uses `yoke claims steering acquire --project P [--doc SLUG] [--reason TEXT]`, `list [--project P] [--active-only]`, and `release CLAIM_ID --reason TEXT`. All dispatch through `/v1/functions/call`.

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
refused. `qa_admission` has no project in scope on purpose: a physical
machine is one resource whichever project drives the run.

**Stickiness is the property that separates these kinds from the rest.**
`migration_serialization` and `qa_admission` are sticky: the stale-session
sweep, the session-end release, and the claim-free end check all skip
them, because the migration and the remote suite keep running after the
session that started them goes quiet. Recovery is the audited human
operator release, never an automatic reclaim. `route_qualification` is
liveness-bound like the backlog kinds — a grant is only valid while its
operator session lives — so the sweep reclaims it normally.

Each claim is addressed by one operator key: `LIVE_DB_MIGRATION:<model>`,
`QA_HOST:<machine>`, and the qualification grant token. The key is the
only handle an operator needs.

Domain API: `yoke_core.domain.coordination_claims` exports `acquire`,
`heartbeat`, `release`, `active_claim`, and `get_claim`, plus the siblings
`coordination_claims_listing` (`list_claims`, `stale_claim_candidates`)
and `coordination_claims_operator` (`operator_release`, human-only).
`yoke_core.domain.coordination_claim_keys` is the only place keys and
targets convert. Read them with `yoke coordination-claim list
[--project P] [--key K] [--item N] [--active-only]`; recover a stranded
one with `yoke coordination-claim release --project P --key K --reason R`,
which emits a WARN `OperatorLeaseRelease` before the release mutation
lands, refuses to run from a hook context, and keeps the operator's words
on the row in `release_reason_intent`. Lifecycle emits `LeaseAcquired`,
`LeaseHeartbeated`, and `LeaseReleased`.

Doctor surfaces stale (heartbeat older than 60 minutes) or orphaned
(holding `harness_sessions.ended_at IS NOT NULL`) live session-held claims
via the `coordination-claims-stale-or-orphan` HC; item-owned migration
territory is excluded, because no session liveness applies to it.
Completed live-apply audit rows whose `source_branch` never reached
`integration_target` show up under `coordination-claims-unmerged-source`.
Recovery still flows through the human-only operator-release path —
neither HC auto-releases.

### BOARD.md Claims column rendering

The Active Harness Sessions and Recent Sessions tables share one Claims column that renders all three primitives as keycap entries. The shapes:

| Primitive               | Active shape                | Example                            |
|---                      |---                          |---                                 |
| work_claim (item)       | `PREFIX-N`                     | `PREFIX-N`                         |
| work_claim (epic task)  | `PREFIX-N T###`                | `PREFIX-N T008`                    |
| work_claim (process)    | `⚙ <process_key>`           | `⚙ FEED`                           |
| work_claim (steering)   | `steering:<slug>`           | `steering:yoke`                    |
| work_claim (other kind) | `<kind>:<compact-scope>`    | `future_kind:{"k":"v"}`            |
| strategy_doc_claim      | `doc:<SLUG>`                | `doc:MISSION`                      |
| work_claim + same-item path_claim decoration | `PREFIX-N 📁<total>`           | `PREFIX-N 📁23`                    |
| path_claim orphan       | `📁<total> (PREFIX-N)`         | `📁5 (PREFIX-N)`                   |
| path_claim process anchor | `📁<total> (⚙ process_key)` | `📁3 (⚙ FEED)`                     |
| coordination claim      | `🔒 <key>`                  | `🔒 QA_HOST:mac-mini-lab`          |
| coordination claim (item-owned) | `🔒 <key> (PREFIX-N)` | `🔒 LIVE_DB_MIGRATION:primary (PREFIX-N)` |

Rules: same-session multiple `path_claims` on the same item roll up into one keycap with the summed declared-path total; coordination claims never decorate work_claims (they stay `🔒` keycaps and are omitted from the work-claim list so they do not also render as `?`); ordering inside a row is work_claims → `doc:<SLUG>` locks → orphan path_claim keycaps → coordination claims. Repeat work claims on the same rendered target and repeat coordination claims on the same key each collapse to the most recent row (one keycap). Steering occupancy is this column, not a separate Steering section. Release reasons are not rendered on Claims — drill into claim detail surfaces for audit history. Released path_claims and coordination claims do not appear on active-session rows. Per-file enumeration is intentionally out of scope — operators drill into per-file detail via `path-claims list --item PREFIX-N`.

### Session Offer

The session-offer endpoint (`POST /v1/sessions/offer`) accepts a session-offer payload, computes the shared scheduler result from the DB, and calls the pure decision engine (`decide_next_action()` from `session.py`) to determine the next action for the offered session. The response is a `NextAction` JSON object.

Scheduler computation (`compute_schedule()` in `scheduler.py`) delegates
frontier classification and ranking to `frontier.py`, resolves `next_step`
from each item's pinned workflow skill binding, honors implementation WIP
eligibility when selecting the assignable step, evaluates `work_claims` for
claim state, and probes truthful SML coherence/staleness across the MISSION,
VISION, MASTER-PLAN, and LANDSCAPE views rendered under `.yoke/strategy/`.

The `service_client.py session-offer` command calls `compute_schedule()` directly (direct DB access, not via HTTP) for shell-accessible use.

API: `POST /v1/sessions/offer`. Service client: `python3 service_client.py session-offer --executor E --provider P --workspace W [--lane L] [--session-id S] [--model M]`.

Yoke-owned `/yoke do` callers omit `--model`; the service client resolves the model from `harness_sessions.model` by `session_id` and falls back to the harness model detector only when the stored row is absent or placeholder-valued. The optional `--model` flag remains for low-level adapter diagnostics that intentionally need an explicit override.
