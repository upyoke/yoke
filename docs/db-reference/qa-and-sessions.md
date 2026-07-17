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
executor_type TEXT NOT NULL -- how it ran: agent, shell, playwright, manual, github-actions, remote-browser
qa_kind TEXT NOT NULL -- what was tested (denormalized from requirement for query convenience)
verdict TEXT -- CHECK: pass | fail | inconclusive | error (nullable until inspection writes it)
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

**Capture vs inspection.** For `browser_smoke` and `browser_diff` runs, the two columns serve distinct concerns:
- `execution_status='captured'` means the daemon successfully saved the expected screenshots to disk.
- `execution_status='capture_failed'` means the daemon errored, an artifact path was missing, a step failed, or completeness check failed.
- `verdict` is set **only after screenshot inspection** (LLM or human evaluation of the screenshot content). Infrastructure success alone never writes `verdict='pass'`.
- Typical lifecycle: orchestrator writes `execution_status='captured', verdict=NULL` -> agent inspects screenshots -> `yoke qa run complete --requirement-id <id> --run-id X --verdict pass|fail` flips verdict in place.

Every downstream gate that filters `verdict='pass'` (status-transition, pre-merge, pre-deploy, flow-gate updates) therefore gates on inspection outcome, not capture.

**Browser run freshness:** For `browser_smoke` and `browser_diff` requirements, the QA gate checks that passing runs are **fresh** — i.e., their `created_at` is at or after the latest commit timestamp on the item's branch. If an Engineer retry changes code after a browser scenario was recorded, the prior passing run is considered stale and does not satisfy the gate. This prevents the gate from accepting screenshots that validated a different version of the deployed app. The freshness check applies only to rows that already carry `verdict='pass'` (i.e., have been inspection-verified); capture-only rows fail the gate on the `verdict='pass'` predicate first and never reach the freshness check. When no branch can be resolved (e.g., items without a worktree), the freshness check is skipped gracefully — it only applies when git context is available.

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

Tracks active harness sessions offering themselves to Yoke for work assignment. Identity fields align with the session-offer contract. Sessions with `ended_at IS NULL` are considered active. Stale sessions (heartbeat older than threshold) are reclaimable.

**Stale-heartbeat threshold (canonical reference).** The reclaim window is config-tunable, not a code literal. Two machine-config keys govern it:

- `session_stale_ttl_minutes` (default `20`) — applies to any executor without a per-executor override.
- `session_stale_ttl_minutes_codex_override` (default `60`) — applies to `codex` and `codex-*` executors. Codex has no true SessionEnd, so between-turn idle is normal; the longer window prevents force-ending sessions whose operator stepped away between turns.

Resolver: `yoke_core.domain.sessions_analytics_core.DEFAULT_STALE_THRESHOLD_MINUTES` (the default) and `EXECUTOR_STALE_TTL_OVERRIDES_MINUTES` (the per-executor map). The per-executor lookup at `yoke_core.domain.sessions_render_reclaim._resolve_effective_ttl` honors `claude-*` and `codex-*` prefix fallbacks. Downstream documentation should cite the config keys above by name rather than the current literal values — values may shift; the key names are stable.

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

The `offer_envelope` column stores the full session-offer JSON including `supported_paths` (list of canonical downstream path names the session can execute), `max_chain_steps`, and the persisted `chain_checkpoint`. When `supported_paths` is non-empty, the decision engine validates the required path against it and returns `escalate` with `escalate_reason: "unsupported_path"` if the path is not supported. See `docs/session-offer-contract.md` for the path derivation mapping.

**Chain checkpoint:** After each `/yoke do` mode handler returns, a `chain_checkpoint` key is written into `offer_envelope` via `update_chain_checkpoint()`. This persists the post-handler state (`step`, `action`, `chainable`, `handler_outcome`, `item_id`, `task_num`, `status`, `required_path`, `completed_at`) so that Step C of the loop can consult durable state rather than prompt-local variables when deciding whether to re-offer. The same envelope's `max_chain_steps` value lets normal `session-end` reject premature cleanup with `CHAIN_PENDING`; `--force` / `force=true` does not bypass that guard. The explicit chain-end override flag plus a non-empty rationale is required and emits `ChainDeclineOverridden`. Sessions holding unreleased claims stay active until the claim lifecycle releases them, the stale-session cleaner (`clean-stale-sessions`) reclaims them, or a human explicitly uses `python3 -m yoke_core.api.service_client claim-release`. Read via `read_chain_checkpoint()` or the `session-checkpoint-read` CLI command.

Indexes: `idx_harness_sessions_lane(execution_lane)`, `idx_harness_sessions_heartbeat(last_heartbeat)`.

Shell access: the Python harness-session CLI (`begin|touch|end|get|list|stale|reclaim`). API: `/v1/sessions` endpoints.

## Table: work_claims

Tracks active harness-session work-unit occupancy through one of three typed targets. Claims with `released_at IS NULL` are active; exclusive claims prevent another session from claiming the same target. The CHECK constraint enforces "exactly one target population per row":

- **Item target** (`target_kind='item'`): `item_id` is the bare integer item id; `epic_id`/`task_num`/`process_key`/`conflict_group` MUST be NULL. This is the shape that backs `/yoke advance`, `/yoke polish`, etc.
- **Epic-task target** (`target_kind='epic_task'`): `epic_id` + `task_num` populated, all other target columns NULL. Reserved for future direct epic-task occupancy; today's epic-task work hangs off the parent item claim.
- **Process target** (`target_kind='process'`): `process_key` (e.g. `STRATEGIZE`, `FEED`, `DOCTOR`) + `conflict_group` populated; all other target columns NULL. Owned by recurring control-plane commands such as `/yoke strategize`, `/yoke feed`, and `/yoke doctor`. The `conflict_group` template `strategy-control-plane:<project>` makes any STRATEGIZE/FEED overlap on the same project reject at acquisition time via the unique partial index.

```sql
id INTEGER PRIMARY KEY
session_id TEXT NOT NULL -- FK to harness_sessions.session_id
target_kind TEXT NOT NULL CHECK(target_kind IN ('item','epic_task','process'))
item_id INTEGER -- bare integer item id (target_kind='item' only)
epic_id INTEGER -- target_kind='epic_task' only
task_num INTEGER -- target_kind='epic_task' only
process_key TEXT -- target_kind='process' only (e.g. STRATEGIZE, FEED)
conflict_group TEXT -- target_kind='process' only; backs the unique partial index
claim_type TEXT NOT NULL DEFAULT 'exclusive' CHECK(claim_type='exclusive')
claimed_at TEXT NOT NULL
last_heartbeat TEXT NOT NULL
released_at TEXT
release_reason TEXT -- completed, released, reclaimed, handed_off, expired, session_ended
```

Indexes: `idx_work_claims_session(session_id)`, `idx_work_claims_item(item_id)`, `idx_work_claims_epic_task(epic_id, task_num)`, `idx_work_claims_process(process_key)`, `idx_work_claims_heartbeat(last_heartbeat)`.

Active-claim exclusivity invariants — three partial unique indexes, each scoped to `released_at IS NULL` so historical released overlap rows remain queryable evidence:

- `idx_work_claims_active_item ON work_claims(item_id) WHERE released_at IS NULL AND target_kind='item'` — at most one unreleased item claim per `item_id`.
- `idx_work_claims_active_epic_task ON work_claims(epic_id, task_num) WHERE released_at IS NULL AND target_kind='epic_task'` — at most one unreleased epic-task claim per `(epic_id, task_num)`.
- `idx_work_claims_active_process_conflict ON work_claims(conflict_group) WHERE released_at IS NULL AND target_kind='process'` — at most one unreleased process claim per `conflict_group` (backs STRATEGIZE/FEED/DOCTOR mutual exclusion).

The item and epic-task indexes are the authoritative storage-level prevention layer for concurrent writers from separate database connections; the application-level `WHERE NOT EXISTS` check inside `claim_work` remains in place for readable holder lookups, but the partial unique indexes are what guarantee two writers cannot both leave unreleased active rows for the same work unit. A losing concurrent writer surfaces as `SessionError("ALREADY_CLAIMED")` with the winning session id preserved in the message.

Shell access: the typed `claim-work` / `release-work-claim` service-client surface (`yoke_core.api.service_client_work_claims`) and the harness-session claim CLI. API: `/v1/sessions/{id}/claims`, `/v1/claims/{id}/release`, `/v1/claims/by-work-unit`.

### Live claim-holder lookup (`who-claims`)

The canonical recipe for "which session currently holds the work claim on `YOK-N`?" is

```sh
python3 -m runtime.harness.harness_sessions who-claims <item-id>
# also reachable as:
python3 -m yoke_core.cli.db_router harness-sessions who-claims <item-id>
```

Both surfaces return the active `work_claims` row (`released_at IS NULL`) joined to its owning `harness_sessions` row, so the operator (or a downstream agent) can see the holder's `session_id`, `executor`, `mode`, and `last_heartbeat` in one call. The typed work-claim model means the lookup matches on `target_kind='item'` plus the bare integer `item_id`; do not write ad-hoc SQL using guessed owner columns, guessed claim-session columns, retired item-claim table names, or generic target columns. The same recipe is the canonical example in the generated agent context packet (`yoke_core.domain.schema_api_context`, topic `claims`).

`work_claims` is the **active session occupancy** primitive — what a harness session is doing right now. It is NOT path/file ownership truth (that lives in `path_claims`) and NOT live shared-operation truth (that lives in `coordination_leases`). Process path claims attribute back to their owning process work-claim through `path_claims.work_claim_id`.

## Table: coordination_leases

Shared-operation lease primitive keyed on `(project_id, lease_key)`. A live row is exclusive ownership of a dangerous shared-state operation for the duration of a single attempt. `LIVE_DB_MIGRATION:<model_name>` is the first consumer; new shared-operation consumers pick their own `lease_key` convention without adding another lock table.

`coordination_leases` is the third claim/lease primitive alongside `work_claims` (active session occupancy) and `path_claims` (repo mutation authority). The three are orthogonal — a single session may hold a work_claim on an item, path_claims on its files, and a coordination_lease on a shared operation concurrently.

```sql
id INTEGER PRIMARY KEY
project_id TEXT NOT NULL
lease_key TEXT NOT NULL              -- e.g. LIVE_DB_MIGRATION:primary
session_id TEXT NOT NULL             -- holder
actor_id TEXT                        -- operator attribution
acquired_at TEXT NOT NULL
heartbeat_at TEXT                    -- last liveness signal
released_at TEXT
release_reason TEXT
```

Indexes: `idx_coordination_leases_live` (unique partial: `(project_id, lease_key) WHERE released_at IS NULL` — enforces exclusive live ownership) plus `idx_coordination_leases_session(session_id)` and `idx_coordination_leases_heartbeat(heartbeat_at)`.

Domain API: `yoke_core.domain.coordination_leases` exports `acquire_lease`, `heartbeat_lease`, `release_lease`, `active_lease`, `get_lease`, plus the sibling `list_leases` / `stale_lease_candidates` (listing diagnostics) and `operator_release` (human-only recovery). Service-client surface: `coordination-lease-{acquire,heartbeat,list,release}` under `python3 -m yoke_core.api.service_client ...`. Lease lifecycle emits `LeaseAcquired`, `LeaseHeartbeated`, `LeaseReleased`, and (operator override only) `OperatorLeaseRelease`.

Doctor surfaces stale (`heartbeat_at` older than 60 minutes) or orphaned (owning `harness_sessions.ended_at IS NOT NULL`) live leases via the `coordination-leases-stale-or-orphan` HC; completed live-apply audit rows whose `source_branch` never reached `integration_target` show up under `coordination-leases-unmerged-source`. Recovery still flows through the human-only operator-release path — neither HC auto-releases.

### BOARD.md Claims column rendering

The Active Harness Sessions and Recent Sessions tables share one Claims column that renders all three primitives as keycap entries. The shapes:

| Primitive               | Active shape                | Example                            |
|---                      |---                          |---                                 |
| work_claim (item)       | `YOK-N`                     | `YOK-N`                         |
| work_claim (epic task)  | `YOK-N T###`                | `YOK-N T008`                    |
| work_claim (process)    | `⚙ <process_key>`           | `⚙ FEED`                           |
| work_claim + same-item path_claim decoration | `YOK-N 📁<total>`           | `YOK-N 📁23`                    |
| path_claim orphan       | `📁<total> (YOK-N)`         | `📁5 (YOK-N)`                   |
| path_claim process anchor | `📁<total> (⚙ process_key)` | `📁3 (⚙ FEED)`                     |
| coordination_lease      | `🔒 <lease_key>`            | `🔒 LIVE_DB_MIGRATION:primary`     |

Rules: same-session multiple `path_claims` on the same item roll up into one keycap with the summed declared-path total; leases never decorate work_claims; ordering inside a row is work_claims → orphan path_claim keycaps → leases. The recently-closed table uses the same shapes plus `(release_reason)` decoration on terminal rows; released path_claims and leases do not appear on active-session rows. Per-file enumeration is intentionally out of scope — operators drill into per-file detail via `path-claims list --item YOK-N`.

### Session Offer

The session-offer endpoint (`POST /v1/sessions/offer`) accepts a session-offer payload, computes the shared scheduler result from the DB, and calls the pure decision engine (`decide_next_action()` from `session.py`) to determine the next action for the offered session. The response is a `NextAction` JSON object.

Scheduler computation (`compute_schedule()` in `scheduler.py`) delegates frontier classification and ranking to `frontier.py`, adds type-aware next-step routing, honors conduct WIP eligibility when selecting the assignable step, evaluates `work_claims` for claim state, and probes truthful SML coherence/staleness across the MISSION, VISION, MASTER-PLAN, and LANDSCAPE views rendered under `.yoke/strategy/`.

The `service_client.py session-offer` command calls `compute_schedule()` directly (direct DB access, not via HTTP) for shell-accessible use.

API: `POST /v1/sessions/offer`. Service client: `python3 service_client.py session-offer --executor E --provider P --workspace W [--lane L] [--session-id S] [--model M]`.

Yoke-owned `/yoke do` callers omit `--model`; the service client resolves the model from `harness_sessions.model` by `session_id` and falls back to `runtime.harness.hook_helpers_model.detect_model()` only when the stored row is absent or placeholder-valued. The optional `--model` flag remains for low-level adapter diagnostics that intentionally need an explicit override.
