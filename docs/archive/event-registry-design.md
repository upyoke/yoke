# Event Registry Design

Version: 1.0.0
Status: Implemented (Sprint 3 — YOK-407, YOK-431)
FR: FR-29 (YOK-407)
Audience: Yoke contributors, event infrastructure maintainers

---

## Purpose

The event registry is a metadata catalog of all known event types in the system. It enables:

1. **Discoverability** -- A single source of truth for what events exist, what they mean, and what context they carry.
2. **Emit-time validation** -- Optional enforcement that emitted events match a registered schema.
3. **Schema evolution tracking** -- Version history per event type showing when fields were added.
4. **Documentation generation** -- Auto-generate event catalog docs from registry data.
5. **Health monitoring** -- Doctor checks can verify events are being emitted as expected (HC-event-gap).

## Table Schema: `event_registry`

```sql
CREATE TABLE IF NOT EXISTS event_registry (
  id INTEGER PRIMARY KEY AUTOINCREMENT,

  -- Identity
  event_name TEXT NOT NULL UNIQUE,
  event_kind TEXT NOT NULL CHECK(event_kind IN ('analytics','system','audit','security','metric')),
  event_type TEXT NOT NULL,
  source_type TEXT NOT NULL CHECK(source_type IN ('agent','backend','frontend','system')),

  -- Documentation
  description TEXT NOT NULL,
  emitter_script TEXT,           -- e.g., 'observe-tool.sh', 'harness-session-start.sh'
  emitter_mechanism TEXT,        -- 'hook_emitted' | 'script_emitted' | 'api_emitted'

  -- Context schema (JSON Schema subset for validation)
  context_schema TEXT,           -- JSON: { "field": "type", ... }
  required_context_fields TEXT,  -- comma-separated field names

  -- Severity
  default_severity TEXT NOT NULL DEFAULT 'INFO',

  -- Lifecycle
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','deprecated','proposed')),
  introduced_version TEXT,       -- e.g., '1.0.0' (when this event was first emitted)
  deprecated_version TEXT,       -- set when status changes to 'deprecated'

  -- Metadata
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Index for common lookups
CREATE INDEX IF NOT EXISTS idx_event_registry_kind ON event_registry(event_kind);
CREATE INDEX IF NOT EXISTS idx_event_registry_source ON event_registry(source_type);
CREATE INDEX IF NOT EXISTS idx_event_registry_status ON event_registry(status);
```

## Registry Rows for Current Events

The following events are emitted by the YOK-407 reference implementation. Each row documents one registered event type.

### ToolCallCompleted

| Field | Value |
|-------|-------|
| event_name | `ToolCallCompleted` |
| event_kind | `system` |
| event_type | `tool_call` |
| source_type | `agent` |
| description | Emitted after every successful tool call in a worker agent session. Captures tool name, command text (Bash), file path (Read/Write/Edit), duration, and exit code. |
| emitter_script | `observe-tool.sh` |
| emitter_mechanism | `hook_emitted` |
| default_severity | `INFO` (elevated to `WARN` when anomaly_flags present) |
| context_schema | `{"tool_name": "string", "command": "string?", "file_path": "string?", "response_preview": "string?"}` |
| required_context_fields | `tool_name` |
| status | `active` |
| introduced_version | `1.0.0` |

### ToolCallFailed

| Field | Value |
|-------|-------|
| event_name | `ToolCallFailed` |
| event_kind | `system` |
| event_type | `tool_call` |
| source_type | `agent` |
| description | Emitted after every failed tool call (PostToolUseFailure hook). Same context as ToolCallCompleted but with error details and severity WARN. |
| emitter_script | `observe-tool.sh` |
| emitter_mechanism | `hook_emitted` |
| default_severity | `WARN` |
| context_schema | `{"tool_name": "string", "command": "string?", "file_path": "string?", "error": "string?", "response_preview": "string?"}` |
| required_context_fields | `tool_name` |
| status | `active` |
| introduced_version | `1.0.0` |

### AgentSessionStarted

| Field | Value |
|-------|-------|
| event_name | `AgentSessionStarted` |
| event_kind | `system` |
| event_type | `session_lifecycle` |
| source_type | `agent` |
| description | Emitted once per session when `harness-session-start.sh` fires on the first UserPromptSubmit hook. Marks the beginning of an agent session for timeline reconstruction. |
| emitter_script | `harness-session-start.sh` |
| emitter_mechanism | `hook_emitted` |
| default_severity | `INFO` |
| context_schema | `{}` |
| required_context_fields | (none) |
| status | `active` |
| introduced_version | `1.0.0` |

### AgentSessionStopped

| Field | Value |
|-------|-------|
| event_name | `AgentSessionStopped` |
| event_kind | `system` |
| event_type | `session_lifecycle` |
| source_type | `agent` |
| description | Emitted when a subagent session ends (SubagentStop hook). Captures final task status, auto-commit metadata, and dispatch context. Multiple emission points cover epic dispatch, issue dispatch, and no-dispatch scenarios. |
| emitter_script | `on-agent-stop.sh` |
| emitter_mechanism | `hook_emitted` |
| default_severity | `INFO` |
| context_schema | `{"final_status": "string?", "auto_committed": "boolean"}` |
| required_context_fields | (none) |
| status | `active` |
| introduced_version | `1.0.0` |

## Anomaly Flag Definitions

Anomaly flags are set on ToolCallCompleted/ToolCallFailed events by `observe-tool.sh`. They are stored as comma-separated values in the `anomaly_flags` column of the `events` table.

| Flag | Detection | Description |
|------|-----------|-------------|
| `nonzero_exit` | Detected | Tool call returned nonzero exit code (Bash only) |
| `generated_view_write` | Detected | Write/Edit to a generated view file (backlog/*.md, BOARD.md, designs/*.md) |
| `nested_cli` | Detected | Command spawned a nested `claude` CLI process |
| `retry_loop` | Registration only | Repeated identical tool calls in short succession (requires cross-event state; not implemented) |
| `hung_subagent` | Registration only | Subagent exceeded expected duration (requires monitoring infrastructure; not implemented) |

## Call Site Audit

All event emission points in the YOK-407 implementation are grep-discoverable. The canonical grep command is:

```sh
grep -rn 'emit-event.sh.*--name\|event_name.*=.*Tool\|event_name.*=.*Agent\|event_name.*=.*Anomaly' .claude/skills/yoke/scripts/
```

### Emission Points

| # | Script | Event Name | Mechanism | Notes |
|---|--------|------------|-----------|-------|
| 1 | `observe-tool.sh` | `ToolCallCompleted` | Direct DB insert (python3) | Bypasses emit-event.sh for <200ms perf. `event_name = 'ToolCallCompleted'` on line 176. |
| 2 | `observe-tool.sh` | `ToolCallFailed` | Direct DB insert (python3) | Same code path as above; name chosen by `is_failure` flag. |
| 3 | `harness-session-start.sh` | `AgentSessionStarted` | `emit-event.sh --name "AgentSessionStarted"` | Line 306. Single call site. Guarded by `[ -f "$_emit_script" ]`. |
| 4 | `on-agent-stop.sh` | `AgentSessionStopped` | `emit-event.sh --name "AgentSessionStopped"` | Lines 143, 157, 258, 272. Four call sites covering: (a) issue dispatch with item_id/task_num, (b) issue dispatch without, (c) epic dispatch with item_id/task_num, (d) epic dispatch without. |

### Grep-Discoverability Verification

**Pattern 1: emit-event.sh --name calls** (session lifecycle events)

```
harness-session-start.sh:306:    --name "AgentSessionStarted"
on-agent-stop.sh:143:    --name "AgentSessionStopped"
on-agent-stop.sh:157:    --name "AgentSessionStopped"
on-agent-stop.sh:258:    --name "AgentSessionStopped"
on-agent-stop.sh:272:    --name "AgentSessionStopped"
```

**Pattern 2: event_name assignment** (tool call events in observe-tool.sh)

```
observe-tool.sh:176:event_name = 'ToolCallFailed' if is_failure else 'ToolCallCompleted'
```

**Note:** `observe-tool.sh` bypasses `emit-event.sh` for performance reasons (single python3 invocation handles JSON build + DB insert to meet the <200ms NFR-1 budget). The event_name is assigned as a string literal, making it grep-discoverable via `event_name.*=.*'ToolCall'`. The `AnomalyDetected` secondary event from the spec (FR-19) is not implemented as a separate event; instead, anomaly information is captured via the `anomaly_flags` column on the primary ToolCallCompleted/ToolCallFailed event.

## Emit-Time Validation

Emit-time validation is implemented via `lint-event-registry.sh`, a PreToolUse hook that intercepts Bash commands containing `emit-event.sh` and validates the `--name` argument against the `event_registry` table.

### Validation Outcomes

| Outcome | Behavior |
|---------|----------|
| Registered (active) | Allow silently |
| Registered (deprecated) | Allow with stderr warning |
| Not registered | Deny with `permissionDecision: "deny"` and a message showing the `registry add` command |

### Graceful Degradation

- If `event_registry` table does not exist: allow all
- If `yoke.db` is not found: allow all
- Only validates direct `emit-event.sh` calls in Bash commands; indirect invocations (called from within another script) are not intercepted

### yoke-db.sh events Registry Subcommands

| Subcommand | Description |
|------------|-------------|
| `registry add <name> --kind K --type T --service S --description D` | Register event type (INSERT OR IGNORE) |
| `registry get <name>` | Show full registry entry |
| `registry list [--status S] [--kind K] [--service S]` | List entries |
| `registry update <name> [--description D] [--severity L] [--status S]` | Update fields |
| `registry deprecate <name>` | Set status to `deprecated` |
| `registry count [--status S]` | Count entries |
| `registry discover` | Grep-discover `emit-event.sh` call sites in codebase |
| `registry audit` | Combined registry health report |
| `registry diff [--verbose]` | Registry vs codebase diff |

### Doctor Health Checks

| Check | Description |
|-------|-------------|
| HC-event-registry-coverage | Stale active entries (registered but not emitted in 30 days) and rogue events (emitted but not registered) |
| HC-event-emission-rate | Verifies events are being emitted when agent sessions are active |
| HC-event-callsite-registry-sync | Discovers `emit-event.sh` call sites and checks each against the registry |

## Deferred: AnomalyDetected Secondary Event

The spec (FR-19) mentions `AnomalyDetected` as a secondary event emitted by `observe-tool.sh` when anomaly flags are present. The current implementation captures anomaly information on the primary event via the `anomaly_flags` column rather than emitting a separate event. This is a design trade-off:

- **Current approach:** Single event per tool call, anomalies as metadata. Simpler, fewer writes, anomaly queryable via `yoke-db.sh events anomalies`.
- **Alternative:** Separate `AnomalyDetected` event per anomaly occurrence. Enables independent severity, independent retention, and event-level anomaly context.

The follow-on epic should evaluate whether `AnomalyDetected` as a separate event adds enough value to justify the additional write overhead.

## Future Event Types (Phase 2 -- Script-Emitted)

These events are planned for the follow-on "Yoke Script-Emitted Events" epic and should be registered when built:

| Event Name | Kind | Type | Emitter |
|------------|------|------|---------|
| `ShepherdVerdictReached` | system | shepherd | `shepherd.sh` (planned) |
| `ConductDispatchStarted` | system | dispatch | `conduct` skill (planned) |
| `ConductDispatchCompleted` | system | dispatch | `conduct` skill (planned) |
| `DeploymentStageStarted` | system | deployment | `deploy-pipeline.sh` (planned) |
| `DeploymentStageCompleted` | system | deployment | `deploy-pipeline.sh` (planned) |
| `BacklogItemTransitioned` | audit | item_lifecycle | `backlog-registry.sh` (planned) |
| `SprintComposed` | audit | sprint_lifecycle | `compose` skill (planned) |
| `MergeCompleted` | system | merge | `merge-worktree.sh` (planned) |
| `PruneCompleted` | system | maintenance | `yoke-db.sh events prune` (planned) |

These follow the naming convention from Section A.4 of the structured logging standard (PascalCase, verb-last).

## Migration Path

1. **Phase 1 (complete):** Events emitted with grep-discoverability ensuring catalog accuracy.
2. **Phase 2 (complete):** `event_registry` table built and populated via `populate-registry.sh`. `lint-event-registry.sh` PreToolUse hook enforces registration at emit time.
3. **Phase 3 (complete):** Doctor health checks (HC-event-registry-coverage, HC-event-emission-rate, HC-event-callsite-registry-sync) enforce registry compliance.
4. **Phase 4 (future):** Per-project registry scoping and context schema validation at emit time.
