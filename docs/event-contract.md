# Event Contract

Canonical source reference for event emission, indexed correlation,
attribution and transaction ownership. The generated [catalog](event-catalog.md)
owns registered names; [schema source](../packages/yoke-core/src/yoke_core/domain/events_schema.py)
owns physical columns. Events are telemetry, never product state authority.

## 1. Event Envelope Structure

Every event is a row in the `events` table. The canonical columns are:

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `event_id` | TEXT (UUID) | Yes | Globally unique, deduplicated by conflict handling |
| `source_type` | TEXT | Yes | `agent`, `backend`, `frontend`, `system`, `script`, `hook`, `skill` |
| `session_id` | TEXT | Yes | Session that emitted the event |
| `severity` | TEXT | Yes | `DEBUG`, `INFO`, `STATUS`, `WARN`, `ERROR`, `FATAL` |
| `event_kind` | TEXT | Yes | Category: `analytics`, `system`, `audit`, `security`, `metric`, `lifecycle`, `workflow` |
| `event_type` | TEXT | Yes | `snake_case` subcategory (e.g., `task_status_change`, `sync_failure`) |
| `event_name` | TEXT | Yes | `PascalCase` unique name (e.g., `TaskStatusChanged`, `SyncFailed`) |
| `event_outcome` | TEXT | No | `completed`, `failed`, `skipped`, or null |
| `org_id` | TEXT | No | Organization identifier |
| `actor_id` | INTEGER | No | Authenticated or named system actor; references `actors(id)` |
| `environment` | TEXT | No | `prod`, `stage`, `local` |
| `service` | TEXT | Yes | Emitting service (default `cli`) |
| `project_id` | INTEGER | No | Indexed FK to `projects(id)`; unresolved telemetry stays global (`NULL`). `project` is envelope attribution. |
| `item_id` | TEXT | No | Backlog item reference (canonical bare-numeric text; display layers may render `YOK-N`) |
| `task_num` | INTEGER | No | Epic task number (when item_id is an epic) |
| `agent` | TEXT | No | Agent name (e.g., `engineer`, `tester`) |
| `tool_name` | TEXT | No | Tool that triggered the event |
| `duration_ms` | INTEGER | No | Execution duration in milliseconds |
| `exit_code` | INTEGER | No | Process exit code (for tool calls) |
| `trace_id` | TEXT | No | Distributed trace correlation ID |
| `tool_use_id` | TEXT | No | Harness-provided tool call ID (dedup key) |
| `anomaly_flags` | TEXT | No | Comma-separated anomaly tags |
| `turn_id` | TEXT | No | Conversation turn within the harness session |
| `hook_event_name` | TEXT | No | Hook phase that produced this event (`PreToolUse`, `PostToolUse`, `PostToolUseFailure`) |
| `client_timing_id` | TEXT | No | Correlation key a hook client minted for its own dispatch; cleared once the client's wall time lands |
| `envelope` | TEXT | No | Full JSON envelope with `context` payload |
| `created_at` | TEXT | Yes | ISO 8601 timestamp (auto-populated) |

### Naming Conventions

| Element | Convention | Examples |
|---------|-----------|----------|
| `event_name` | PascalCase, verb-past-tense | `TaskStatusChanged`, `VerdictRendered`, `ConductBatchCompleted` |
| `event_type` | snake_case, noun-phrase | `task_status_change`, `verdict_rendered`, `conduct_batch_complete` |
| `event_kind` | lowercase enum | `lifecycle`, `workflow`, `analytics`, `system`, `audit`, `security`, `metric` |
| Field names | snake_case | `item_id`, `session_id`, `from_status` |
| Timestamps | ISO 8601 UTC with `Z` suffix | `2026-03-15T14:30:00Z` |

### event_kind Taxonomy

| Kind | Purpose | Examples |
|------|---------|---------|
| `analytics` | User/product usage telemetry | `PageViewed`, `FeatureUsed` |
| `system` | Runtime, harness, sync, and session operations | `HarnessToolCallStarted`, `HarnessToolCallCompleted`, `HarnessSessionSentFirstUserPromptSubmit`, `SyncFailed` |
| `audit` | Reviewable guardrail and policy decisions | `HarnessToolCallDenied` |
| `security` | Auth, access control events | (reserved) |
| `metric` | Numeric measurements | (reserved) |
| `lifecycle` | State machine transitions | `TaskStatusChanged` |
| `workflow` | Orchestration milestones | `VerdictRendered`, `DependencyGateEvaluated`, `DbClaimAmended` |

`event_kind` is the semantic class of the event, not another source axis. If Yoke eventually introduces a dedicated `harness` kind, that should be handled as an explicit taxonomy migration rather than inferred from `source_type`.

### Correlation Columns

All harness correlation fields are first-class indexed columns on the `events` table:

- `tool_use_id` -- harness-provided tool call ID; used as a dedup key (`UNIQUE INDEX ON (tool_use_id, event_name) WHERE tool_use_id IS NOT NULL`)
- `session_id` -- the canonical harness session join key for session-scoped queries
- `turn_id` -- conversation turn within the session
- `hook_event_name` -- the hook phase that produced this event (`PreToolUse`, `PostToolUse`, `PostToolUseFailure`)
- `client_timing_id` -- the key a hook client minted before it ran, so the wall time it reports afterwards finds its dispatch row by an indexed probe (`INDEX ON (client_timing_id) WHERE client_timing_id IS NOT NULL`); the completing update clears it, so the partial index holds only the reports still in flight

These columns are populated at emit time by the observe helper and denial-path observer. Correlate a row through one of them, never by matching a substring of `envelope` with LIKE: `envelope` has no index over its contents, so such a query reads every row its other predicates admit, which is how one telemetry lookup took the production connection pool. `HC-events-envelope-like-scan` enforces that. Historical rows were backfilled by the events-backfill migration.

### Envelope JSON Structure

The `envelope` column stores a full JSON object. The `context` key holds event-specific data. Top-level fields mirror queryable columns for downstream consumers that parse JSON.

New envelopes omit the retired human-user key. Historical envelopes are immutable and may retain that key with a null value; consumers must ignore it and use `actor_id` for engine identity.

`ItemStatusChanged`, `QARunCompleted`, and `QARunCaptured` override caller-supplied attribution with the emitting call's resolved acting identity (dispatcher binding, then ambient session; `actor_id` from `harness_sessions`). When no session exists, `session_id` and `actor_id` stay empty. Historical unattributed rows remain unchanged and are distinguishable by their empty fields.

```json
{
 "event_id": "a1b2c3d4-...",
 "event_name": "TaskStatusChanged",
 "event_kind": "lifecycle",
 "event_type": "task_status_change",
 "severity": "INFO",
 "source_type": "system",
 "service": "cli",
 "project": "yoke",
 "session_id": "...",
 "item_id": "42",
 "task_num": 3,
 "created_at": "2026-03-15T14:30:00Z",
 "context": {
 "detail": {
 "from_status": "implementing",
 "to_status": "reviewing-implementation",
 "note": "Engineer completed implementation"
 }
 }
}
```

### Tool-call context and payload bounds

`observe_event_emission.build_envelope` owns completion/failure/structured-exit
`context.detail`: `tool_name`, `tool_input` (command or file path),
`tool_response_preview`, `error`, `attribution_source`, `hook_event`,
`timing_status`, `actor_role`, and optional decision metadata. Parent calls omit
`actor_role`; dispatched calls identify their role within the parent session.
Correlation, outcome, exit code and duration are indexed/top-level fields;
missing timing is a named unknown, not an instantaneous call. Started and denial
owners have their own registered context contracts.

The observer bounds command input/error to 2048 characters and response preview
to 512. If serialized detail exceeds 4096 UTF-8 bytes, it shrinks those fields
to 1024/1024/256 respectively. Above 65536 envelope bytes it replaces detail
with the tool name and `truncated: true`, and adds `_truncated: true`.
These are character cuts inside byte-size triggers; never report them as token
limits or promise that full tool output was retained. `events_schema` enforces
backend-specific valid JSON for non-null envelopes.

Observer insertion projects activity into session state independently of
telemetry retention. A missing events table does not suppress that state;
ordinary insertion writes the row and idempotent activity projection together.
Product readers use the state projection, never events as inferred authority.

### item_id Format

The canonical format for `events.item_id` is bare numeric text (for example `42`). Display layers may render `YOK-N`, but persisted and programmatic event item references are numeric text. the events-backfill migration converges historical prefixed rows to numeric text.

### Required and recommended attribution

Required physical columns are listed above; a required session field may carry
an empty/sentinel value when identity is unavailable. Every kind needs envelope
project attribution when resolvable; indexed `project_id` remains nullable.
Recommended fields are `item_id` for lifecycle/workflow/audit, `task_num` for
lifecycle, and `turn_id`/`hook_event_name` for analytics/system/audit. Analytics
also recommends `tool_name`, `duration_ms`, `exit_code`, `agent`, and
`tool_use_id`. Other per-event context is contract-owned, not universally required.

## 2. Execution Context Fields

Emission resolves available attribution without inventing missing identity.

### Context Resolution Chain

When an event is emitted, execution context is resolved in this order:

1. **Worktree dispatch context.** `resolve_dispatch_context()` in
   `yoke_core.hooks.helpers_session_id` joins
   `epic_dispatch_chains.item_worktree_id` to `item_worktrees.id` and matches
   the lane's `path` to the harness project directory (exactly or as an
   ancestor). Returns `epic_id | task_num | item_id`.

2. **Unique item-lane fallback.** If no dispatch chain matches, the function
   joins `items.id` to `item_worktrees.item_id` and resolves a single active
   in-flight item whose lane branch or path matches. Returns `item_id` without
   `task_num`.

3. **Explicit tool reference extraction.** The observe hook can attribute a tool call from an unambiguous item reference in a Bash command or an item-scoped worktree path.

4. **Main-session DB-backed attribution.** In main-repo sessions, the observe hook consults `harness_sessions.current_item_id` for session-scoped attribution, then falls back to a single active non-epic item, then to `harness_sessions.recent_item_id` (30-min window).

### Fields Populated by Context

| Field | Source | Coverage |
|-------|--------|----------|
| `item_id` | Dispatch chain, worktree fallback, explicit tool ref, or main-session fallbacks | Best-effort; strongest in worktree contexts |
| `task_num` | Dispatch chain only (epic tasks) | Populated for all epic task work |
| `project` | Dispatch chain/item project context, explicit project context, or the current checkout's machine-config project mapping when available | Setup-dependent; no repo config default |
| `agent` | `$YOKE_AGENT` env var set by agent dispatch | Populated for all agent sessions |
| `session_id` | Ambient chain: `$YOKE_SESSION_ID`, then the session variables of the harness family the process tree names, then that family's process-anchor ancestry registry, then `unknown` (`yoke_core.domain.session_ambient_identity`). A surface that resolves nothing records its declared empty/sentinel value; no surface invents an id. | Always populated |

### Emitting Events with Context

When emitting manually through the CLI, pass context fields explicitly:

```sh
yoke events emit \
 --name "TaskStatusChanged" \
 --kind lifecycle \
 --type task_status_change \
 --source-type system \
 --severity INFO \
 --outcome completed \
 --item PREFIX-N \
 --task-num 3 \
 --context '{"from_status":"implementing","to_status":"reviewing-implementation","note":"..."}'
```

Indexed `events.project_id` uses `resolve_envelope_project_id_for_event` on both the native writer and `cmd_insert`: context `project_id` / `detail.project_id`, then the registered session project for `SESSION_SCOPED_EVENT_TYPES` (including `tool_call` denials), then the boundary project token. `cmd_insert` builds that input from row identity plus parseable envelope context; stored envelope session/type/project never replace the row. Unresolvable tokens stay global (`NULL`). Scripts must still pass context fields the observe hook would populate.

If `--project` is omitted but `--item` is present, the CLI emitter resolves project from the `items` row. Otherwise it uses explicit caller environment or checkout binding; unresolved telemetry remains global (`NULL`). A session-scoped event follows its registered session project.

`yoke_core.domain.events.emit_event` receives bare numeric `item_id` values;
the CLI resolves its complete public `--item` reference first. Stored `events.item_id` values are canonical bare-numeric text.

---

## Domain event contracts

Deployment and QA events use the same ledger with registered kind/type/name and
`context.detail` contracts. The [catalog](event-catalog.md) owns discovery;
[deployment records](public/reference/db-reference/deployment-run-records.md)
remain durable state/evidence independent of telemetry retention.

## 4. Event Naming Registry

All event names MUST be registered in the `event_registry` table before first emission. The `yoke_core.domain.observe` (lint-event-registry guardrail) PreToolUse hook enforces this at development time.

### Registry metadata and catalog

`events_schema` owns `event_registry`: event name, kind, type, owner service,
description, optional context schema, default severity, added-in metadata and
active/deprecated status. It has no timestamp columns; lifecycle observations
belong in the ledger. Consult the generated [full catalog](event-catalog.md)
instead of maintaining another roster here.

`HarnessSessionStopped` is emitted by the agent-stop lifecycle hook; its context includes `stop_reason` with the live values `completed`, `auto_committed`, and `unexpected_stop`.

`HookGuardrailEvaluated`, `HookExecutionFailed`, and `HookDispatchTelemetry` are runner-native emissions from `yoke_core.hooks.telemetry` (see `emit_hook_guardrail_evaluated`, `emit_hook_execution_failed`, `emit_hook_dispatch_telemetry`). `HookDispatchDeduplicated` joins them from `yoke_core.hooks.dispatch_dedup`, emitted by the run half that owns the telemetry tail when a harness delivered one lifecycle event twice. Those four are the only hook-runner telemetry names that exist as registered events.

Ordinary in-process and relayed chains flush these three together over ONE shared connection (`hook_emit_connection`) and pass `transactional=True`; that explicit batch boundary commits before it closes. A resident read-only chain uses the observation endpoint's ordered, idempotent batch instead. Normal `emit_event(conn=...)` calls commit successful rows themselves, so closing or rolling back the caller connection cannot silently discard an event. Use `transactional=True` only when the event must ride the caller's state transaction, whose owner then commits or rolls back both together.
QA requirement creation is the worked example: the plan-case snapshot, the merge-gate CI requirement, and the seeded no-tests floor each write their row into a transaction a later caller commits, so `QARequirementCreated` rides it too and no requirement is durable while dark; that mode raises rather than returning when it cannot record.
`HC-event-family-liveness` compares recent durable activity with expected event names strictly as a telemetry audit, and no product path reads events as state. A pair may name the column separating its table's write paths; the check then pairs each row with its own event and groups by that column, so one emitting path cannot answer for a silent sibling sharing the table.

`HookDispatchTelemetry` context additionally carries `driver_pid`,
`driver_ppid`, and `driver_origin` — the process that DROVE the invocation.
Over the https relay that is the client's own hook child, which self-reports
its pids in `payload_extra` (`yoke_contracts.hook_driver_process`), because
the evaluating server's `os.getpid()` names a shared API worker rather than
the caller. `driver_origin` says which of the two answered: `client` for a
relayed self-report, `local` where the evaluating process is itself the
driver.

It also carries `evaluator` (`resident` or `inprocess`), `resident_warm_duration_ms`, and `client_wall_ms`. The client-owned wall time
starts at interpreter process creation and ends immediately before final stdout; it is always at least the dispatch row's server `duration_ms`.
When resident delivery is unavailable and the canonical in-process fallback
runs, `evaluator_fallback_reason` names that degradation.
Guard-free read-only hooks retain this exact event contract when the resident
persists their tool and dispatch events through the ordered asynchronous
observation batch.

**Suppression-token audit evidence is NOT a separate event.** Lint guardrails honor `# lint:no-*-check` suppression tokens by recording the attempt on the *existing* `HarnessToolCallDenied` row with `event_outcome='suppression_attempted'`. No separate hook suppression event is registered or emitted; observers querying suppression activity filter `HarnessToolCallDenied` by `event_outcome`.

### Registering New Events

Registry mutation is a source-dev/admin boundary, not an installed external-project recipe. Add new event names to the authoritative registry seed/discovery source in the Yoke checkout, run the registry population flow from that checkout, and commit the resulting `docs/event-catalog.md` update. DB-admin one-offs stay in operator-debug runbooks until a product `yoke events registry ...` writer exists.

### Registry Lifecycle

- **active** -- Event is in production use. Emission is allowed.
- **deprecated** -- Event is phased out. Emission triggers a warning but is not blocked. Consumers should stop depending on it.
- Removing a registry entry blocks emission entirely (lint hook denies unregistered names).

---

## 5. Migration Guidance

Pure-log tables are consolidated into the `events` table. Current read and write paths should use direct `events` access; phased cutovers use a temporary compatibility view that is deleted once callers converge. The `shepherd_verdicts` state table emits `VerdictRendered` on write while retaining its table.

Governed cutover, temporary compatibility-view design, domain-state emission
and unified-timeline examples live in [event-contract/migration-guidance.md](event-contract/migration-guidance.md).

## 6. Write-Time Isolation & Querying Guidance

The live `events` ledger is production telemetry. Synthetic test rows must not land in it under any normal workflow. Write-time isolation is enforced by the native emitter and CLI owner via `YOKE_EVENTS_ISOLATION=1`, with explicit escape hatches (Postgres `yoke_test_*` authority, `YOKE_EVENTS_CAPTURE` + `YOKE_EVENTS_FILE`, intentional `synthetic_smoke` lineage marker, explicit `conn=` arguments).

### Synthetic-Row Cleanup Guidance

See [cleanup guidance](event-contract/isolation-and-querying.md#synthetic-row-cleanup-guidance) before deleting rows. The same guide covers [sentinel session IDs](event-contract/isolation-and-querying.md#sentinel-session-ids), [null item references](event-contract/isolation-and-querying.md#rows-with-null-item_id), and the isolation/query contracts above.
