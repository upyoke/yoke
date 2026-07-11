# Event Contract

> Canonical reference for emitting and consuming events in the Yoke event platform.
> Downstream epics (DR-1, QA-1) and all internal scripts MUST follow this contract.

Version: 1.0.0
Status: Active

---

## Table of Contents

- [1. Event Envelope Structure](#1-event-envelope-structure)
- [2. Execution Context Fields](#2-execution-context-fields)
- [3. Reserved Fields for DR-1 / QA-1](#3-reserved-fields-for-dr-1--qa-1)
- [4. Event Naming Registry](#4-event-naming-registry)
- [5. Migration Guidance](#5-migration-guidance)
- [6. Write-Time Isolation & Querying Guidance](#6-write-time-isolation--querying-guidance)

---

## 1. Event Envelope Structure

Every event is a row in the `events` table. The canonical columns are:

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `event_id` | TEXT (UUID) | Yes | Globally unique, deduplicated by conflict handling |
| `source_type` | TEXT | Yes | `agent`, `backend`, `frontend`, `system`, `script`, `hook`, `skill` |
| `session_id` | TEXT | Yes | Session that emitted the event |
| `severity` | TEXT | Yes | `DEBUG`, `INFO`, `WARN`, `ERROR`, `FATAL` |
| `event_kind` | TEXT | Yes | Category: `analytics`, `system`, `audit`, `security`, `metric`, `lifecycle`, `workflow` |
| `event_type` | TEXT | Yes | `snake_case` subcategory (e.g., `task_status_change`, `sync_failure`) |
| `event_name` | TEXT | Yes | `PascalCase` unique name (e.g., `TaskStatusChanged`, `SyncFailed`) |
| `event_outcome` | TEXT | No | `completed`, `failed`, `skipped`, or null |
| `org_id` | TEXT | No | Organization identifier |
| `actor_id` | INTEGER | No | Authenticated engine actor; references `actors(id)` |
| `environment` | TEXT | No | `production`, `staging`, `development` |
| `service` | TEXT | Yes | Emitting service (default `cli`) |
| `project` | TEXT | Yes | Project scope (default `yoke`) |
| `item_id` | TEXT | No | Backlog item reference (canonical bare-numeric text; display layers may render `YOK-N`) |
| `task_num` | INTEGER | No | Epic task number (when item_id is an epic) |
| `agent` | TEXT | No | Agent name (e.g., `engineer`, `tester`) |
| `tool_name` | TEXT | No | Tool that triggered the event |
| `duration_ms` | INTEGER | No | Execution duration in milliseconds |
| `exit_code` | INTEGER | No | Process exit code (for tool calls) |
| `trace_id` | TEXT | No | Distributed trace correlation ID |
| `parent_id` | TEXT | No | Parent event ID for causal chains |
| `tool_use_id` | TEXT | No | Harness-provided tool call ID (dedup key) |
| `anomaly_flags` | TEXT | No | Comma-separated anomaly tags |
| `turn_id` | TEXT | No | Conversation turn within the harness session |
| `hook_event_name` | TEXT | No | Hook phase that produced this event (`PreToolUse`, `PostToolUse`, `PostToolUseFailure`) |
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

These columns are populated at emit time by the observe helper and denial-path observer. Historical rows were backfilled by the events-backfill migration.

### Envelope JSON Structure

The `envelope` column stores a full JSON object. The `context` key holds event-specific data. Top-level fields mirror queryable columns for downstream consumers that parse JSON.

New envelopes omit the retired human-user key. Historical envelopes are
immutable and may retain that key with a null value; consumers must ignore it
and use `actor_id` for engine identity.

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

### Canonical context.detail Shape for Tool-Call Events

Tool-call events (`HarnessToolCallStarted`, `HarnessToolCallCompleted`, `HarnessToolCallFailed`, `HarnessToolCallStructuredExit`, `HarnessToolCallDenied`) use a consistent `context.detail` shape:

```json
{
 "context": {
 "detail": {
 "tool": "Bash",
 "tool_use_id": "call_abc123",
 "hook_event": "PostToolUse",
 "command_preview": "npm test",
 "exit_code": 0,
 "duration_ms": 342,
 "output_bytes": 4096,
 "anomaly_flags": "nonzero_exit",
 "item_id": "42",
 "task_num": 3,
 "agent": "engineer",
 "session_id": "claude-code-20260315T143000Z-12345"
 }
 }
}
```

Fields vary by event: `HarnessToolCallStarted` omits `exit_code`/`duration_ms`/`output_bytes`; `HarnessToolCallDenied` includes `denial_reason` and `lint_check` instead.

### Truncation Rules

Envelope payloads are subject to size limits to prevent DB bloat:

- `command_preview` in `context.detail` is truncated to 200 characters for Bash tool calls
- `output_bytes` records the original output size; the actual output is not stored in the envelope
- `envelope` column has a `CHECK(envelope IS NULL OR json_valid(envelope))` constraint -- truncation must preserve valid JSON
- The `observe.py` emitter applies truncation before INSERT; downstream consumers can rely on `json_valid(envelope)` always being true

### item_id Format

The canonical format for `events.item_id` is bare numeric text (for example `42`). Display layers may render `YOK-N`, but persisted and programmatic event item references are numeric text. the events-backfill migration converges historical prefixed rows to numeric text.

### Required vs Optional Fields Per event_kind

| Field | analytics | system | lifecycle | workflow | audit | security | metric |
|-------|-----------|--------|-----------|----------|-------|----------|--------|
| `event_id` | **req** | **req** | **req** | **req** | **req** | **req** | **req** |
| `source_type` | **req** | **req** | **req** | **req** | **req** | **req** | **req** |
| `session_id` | **req** | **req** | **req** | **req** | **req** | **req** | **req** |
| `event_kind` | **req** | **req** | **req** | **req** | **req** | **req** | **req** |
| `event_type` | **req** | **req** | **req** | **req** | **req** | **req** | **req** |
| `event_name` | **req** | **req** | **req** | **req** | **req** | **req** | **req** |
| `severity` | **req** | **req** | **req** | **req** | **req** | **req** | **req** |
| `item_id` | opt | opt | **rec** | **rec** | **rec** | opt | opt |
| `task_num` | opt | opt | **rec** | opt | opt | opt | opt |
| `project` | **req** | **req** | **req** | **req** | **req** | **req** | **req** |
| `tool_name` | **rec** | opt | opt | opt | opt | opt | opt |
| `duration_ms` | **rec** | opt | opt | opt | opt | opt | opt |
| `exit_code` | **rec** | opt | opt | opt | opt | opt | opt |
| `agent` | **rec** | opt | opt | opt | opt | opt | opt |
| `tool_use_id` | **rec** | opt | opt | opt | opt | opt | opt |
| `turn_id` | **rec** | **rec** | opt | opt | **rec** | opt | opt |
| `hook_event_name` | **rec** | **rec** | opt | opt | **rec** | opt | opt |

Legend: **req** = required, **rec** = recommended, opt = optional.

---

## 2. Execution Context Fields

explicit execution context propagation so events carry attribution metadata automatically was introduced.

### Context Resolution Chain

When an event is emitted, execution context is resolved in this order:

1. **Worktree dispatch context.** `resolve_dispatch_context()` in `hook-helpers.sh` queries `epic_dispatch_chains` for a chain whose `worktree_path` matches `$CLAUDE_PROJECT_DIR`. Returns `epic_id | task_num | item_id`.

2. **Non-epic worktree fallback.** If no dispatch chain matches (e.g., standalone item work in a worktree), the function queries `items` for a single non-epic in-flight item whose `worktree` column matches. Returns `item_id` without `task_num`.

3. **Explicit tool reference extraction.** The observe hook can attribute a tool call from an unambiguous item reference in a Bash command or an item-scoped worktree path.

4. **Main-session DB-backed attribution.** In main-repo sessions, the observe hook consults `harness_sessions.current_item_id` for session-scoped attribution, then falls back to a single active non-epic item, then to `harness_sessions.recent_item_id` (30-min window).

### Fields Populated by Context

| Field | Source | Coverage |
|-------|--------|----------|
| `item_id` | Dispatch chain, worktree fallback, explicit tool ref, or main-session fallbacks | Best-effort; strongest in worktree contexts |
| `task_num` | Dispatch chain only (epic tasks) | Populated for all epic task work |
| `project` | Dispatch chain/item project context, explicit project context, or the current checkout's machine-config project mapping when available | Setup-dependent; no repo config default |
| `agent` | `$YOKE_AGENT` env var set by agent dispatch | Populated for all agent sessions |
| `session_id` | Ambient chain: `$YOKE_SESSION_ID` → `$CLAUDE_SESSION_ID` → `$CODEX_THREAD_ID` → process-anchor ancestry registry → `unknown` (`yoke_core.domain.session_ambient_identity`) | Always populated |

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
 --item-id "42" \
 --task-num 3 \
 --context '{"from_status":"implementing","to_status":"reviewing-implementation","note":"..."}'
```

The observe hook automatically populates `item_id`, `task_num`, `project`, and `agent` from the resolved execution context. Source-dev/admin scripts that emit events outside the hook path must pass these fields explicitly.

If `--project` is omitted but `--item-id` is present, `yoke_core.domain.events.emit_event` resolves the project from the referenced `items` row before falling back to the default `yoke` project. This keeps cross-project lifecycle telemetry aligned even when legacy call sites only pass `--item-id`.

`yoke_core.domain.events.emit_event` should be called with bare numeric `--item-id` values. Stored `events.item_id` values are canonical bare-numeric text.

---

## 3. Reserved Fields for DR-1 / QA-1

Downstream epics (DR-1 deployment events, QA-1 review events) emit through the existing `events` table with reserved `event_kind` / `event_type` / `event_name` / `context.detail.*` conventions. The full reserved-field tables and the "How to emit a new domain event" walkthrough live in [event-contract/reserved-fields-dr1-qa1.md](event-contract/reserved-fields-dr1-qa1.md).

---

## 4. Event Naming Registry

All event names MUST be registered in the `event_registry` table before first emission. The `yoke_core.domain.observe` (lint-event-registry guardrail) PreToolUse hook enforces this at development time.

### Registry Table Schema

```sql
CREATE TABLE event_registry (
 event_name TEXT PRIMARY KEY, -- PascalCase event name
 event_kind TEXT NOT NULL,
 event_type TEXT NOT NULL,
 owner_service TEXT NOT NULL,
 description TEXT NOT NULL,
 context_schema TEXT, -- optional JSON schema for context payload
 severity_default TEXT NOT NULL DEFAULT 'INFO',
 added_in TEXT, -- YOK-N or version when added
 status TEXT NOT NULL DEFAULT 'active' -- 'active' | 'deprecated'
);
```

The schema matches the production DDL in `yoke_core.domain.events_writes`. Timestamps are NOT columns on `event_registry` — the registry is static metadata; lifecycle changes are recorded as events in the main ledger.

### Current Registered Events

| Event Name | Kind | Type | Owner | Status |
|------------|------|------|-------|--------|
| `HarnessToolCallStarted` | system | tool_call | yoke_core.domain.observe_pre | active |
| `HarnessToolCallCompleted` | system | tool_call | yoke_core.domain.observe | active |
| `HarnessToolCallFailed` | system | tool_call | yoke_core.domain.observe | active |
| `HarnessToolCallDenied` | audit | tool_call | runtime.harness.hook_runner.telemetry (shared emit_denial_event helper) | active |
| `HarnessToolCallStructuredExit` | system | tool_call | yoke_core.domain.observe | active |
| `HarnessLifecycleMutationDetected` | system | tool_call | yoke_core.domain.observe | active |
| `HookDispatchTelemetry` | system | hook_dispatch | runtime.harness.hook_runner | active |
| `HookExecutionFailed` | system | hook_execution_failure | runtime.harness.hook_runner | active |
| `HookGuardrailEvaluated` | system | hook_guardrail_evaluated | runtime.harness.hook_runner | active |
| `HarnessSessionSentFirstUserPromptSubmit` | system | session_lifecycle | runtime.harness.hook_runner | active |
| `HarnessSessionStopped` | system | session_lifecycle | agent_stop | active |
| `TaskStatusChanged` | lifecycle | task_status_change | epic-db | active |
| `SyncFailed` | system | sync_failure | sync-helper | active |
| `VerdictRendered` | workflow | verdict_rendered | shepherd | active |
| `GitHubCloseFailure` | system | github_sync | cli | active |
| `IssueMigrated` | system | github_sync | cli | active |

For the full catalog with descriptions, see `docs/event-catalog.md` (auto-generated by the source-dev registry population tool).
`HarnessSessionStopped` is emitted by the agent-stop lifecycle hook; its context includes `stop_reason` with the live values `completed`, `auto_committed`, and `unexpected_stop`.

`HookGuardrailEvaluated`, `HookExecutionFailed`, and `HookDispatchTelemetry` are runner-native emissions from `runtime.harness.hook_runner.telemetry` (see `emit_hook_guardrail_evaluated`, `emit_hook_execution_failed`, `emit_hook_dispatch_telemetry`). They are the only hook-runner telemetry names that exist as registered events.

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

The seven-step migration pattern, compatibility-view COALESCE design, domain-state emission pattern, and unified-timeline query examples live in [event-contract/migration-guidance.md](event-contract/migration-guidance.md).

---

## 6. Write-Time Isolation & Querying Guidance

The live `events` ledger is production telemetry. Synthetic test rows must not land in it under any normal workflow. Write-time isolation is enforced by the native emitter and CLI owner via `YOKE_EVENTS_ISOLATION=1`, with explicit escape hatches (Postgres `yoke_test_*` authority, legacy file-backed `YOKE_DB` test paths, `YOKE_EVENTS_CAPTURE` + `YOKE_EVENTS_FILE`, intentional `synthetic_smoke` lineage marker, explicit `conn=` arguments).

Full coverage — escape-hatch table, pytest autouse fixture, smoke-row tagging, legacy query-time filter, synthetic-row cleanup, sentinel session IDs (`unknown`, `migration-zero-legacy`, `status-events-backfill`), null-`item_id` rows, and the `migrate-events-backfill` / `migrate-events-correlation` normalization scripts — lives in [event-contract/isolation-and-querying.md](event-contract/isolation-and-querying.md).
