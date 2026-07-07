# Structured Logging Standard -- Cross-Stack Event Specification

Version: 1.0.0
Status: Active
Audience: All system components (agent scripts, backend services, frontend clients)

---

## Table of Contents

- [Section A: Canonical Event Envelope](#section-a-canonical-event-envelope) (in this file)
- Section B: [Property Group Definitions](structured-logging-standard/property-groups.md)
- Section C: [Full Envelope Composition Per Source Type](structured-logging-standard/source-type-composition.md)
- Section D: Implementation Templates Per Source Type — [Python](structured-logging-standard/python-templates.md), [JS/TS](structured-logging-standard/js-ts-template.md)
- Section E: [Marketing Attribution Template](structured-logging-standard/marketing-attribution.md)
- Section F: [Agent Session Transcript Pattern](structured-logging-standard/agent-session-pattern.md)
- Appendix: [Event Taxonomy, Severity, Correlation, Versioning](structured-logging-standard/taxonomy-appendix.md)

---

## Section A: Canonical Event Envelope

Every event in the system -- regardless of source -- conforms to a single JSON envelope. The envelope has two parts: **property groups** at the root level (universal, queryable fields) and a **context** object (event-specific payload). Any consumer can filter by root-level fields without parsing `context`.

### Naming Conventions

All fields across all source types and all languages MUST follow these rules:

| Rule | Convention | Examples |
|---|---|---|
| Field names | `snake_case` | `event_name`, `session_id`, `user_email` |
| Timestamps | ISO 8601 UTC, always with `Z` suffix | `2026-03-12T14:30:00.000Z` |
| Enums | Lowercase strings | `"info"`, `"agent"`, `"completed"` |
| IDs | UUIDs or deterministic slugs, never exposed integers | `"a1b2c3d4-..."`, `"yoke"` |
| Booleans | `is_` prefix | `is_retryable`, `is_anonymous`, `is_bot` |
| Durations | `_ms` suffix (integer milliseconds) | `duration_ms`, `ttfb_ms` |
| Counts | `_count` suffix (integer) | `item_count`, `retry_count` |

### Top-Level Discriminator

Every event carries a `source_type` field at the root level:

```
source_type: "agent" | "backend" | "frontend" | "system" | "script" | "hook" | "skill"
```

This enum enables cross-source queries without reasoning about `service` values. For example: `SELECT * FROM events WHERE source_type = 'frontend'` returns all client-side events regardless of which frontend service emitted them. `event_kind` is a separate semantic axis; it is not another emitter-source field.

### Minimal Envelope Structure

```json
{
 "event_id": "uuid-v4",
 "event_name": "PascalCaseEventName",
 "event_kind": "analytics|system|audit|security|metric|lifecycle|workflow",
 "event_type": "free-string-project-specific",
 "event_time": "2026-03-12T14:30:00.000Z",
 "event_outcome": "completed|failed|skipped|null",
 "severity": "DEBUG|INFO|WARN|ERROR|FATAL",
 "source_type": "agent|backend|frontend|system|script|hook|skill",
 "duration_ms": 142,

 "environment": "production",
 "service": "cli",
 "service_version": "1.0.0",
 "project": "yoke",

 "session_id": "uuid-or-fallback",
 "trace_id": "optional-uuid",
 "parent_id": "optional-uuid",
 "request_id": "optional-uuid",

 "context": {
 "event_specific_key": "event_specific_value"
 }
}
```

### Anomaly Flag Enum

The `anomaly_flags` field is a comma-separated string of canonical anomaly flags. These flags are consistently named across all emitters and are cross-queryable.

| Flag | Description | Detection |
|---|---|---|
| `nonzero_exit` | Tool call returned nonzero exit code | Active -- check `exit_code <> 0` |
| `generated_view_write` | Write to a generated view file (e.g., `.yoke/BOARD.md`) | Active -- check file path patterns |
| `retry_loop` | Repeated identical tool calls within a session | Active -- compare recent tool calls |
| `nested_cli` | Spawned a nested `claude` CLI process | Active -- check command for `claude` invocation |
| `hung_subagent` | Subagent exceeded expected duration | Registration only -- no detection in this version |

Anomaly flags are stored as a comma-separated TEXT field: `"nonzero_exit,retry_loop"`. Query with `anomaly_flags LIKE '%nonzero_exit%'` or use `python3 -m yoke_core.cli.db_router events anomalies` for structured access.

### Root-Level Query Columns

For query performance, the following fields are promoted from `context` to root-level columns in the `events` table:

- `tool_name` (TEXT) -- the tool invoked (Bash, Read, Write, Edit, Grep, Glob, Agent)
- `exit_code` (INTEGER) -- tool exit code (null for non-Bash tools)
- `agent` (TEXT) -- the agent that emitted the event
- `item_id` (TEXT) -- backlog item ID (canonical bare-numeric text; display may render `YOK-N`)
- `task_num` (INTEGER) -- epic task number
- `user_id` (TEXT) -- user identifier
- `org_id` (TEXT) -- organization identifier
- `tool_use_id` (TEXT) -- harness-provided tool call ID (dedup key, indexed)
- `turn_id` (TEXT) -- conversation turn within the harness session
- `hook_event_name` (TEXT) -- hook phase that produced this event (`PreToolUse`, `PostToolUse`, `PostToolUseFailure`)

### /api/events Endpoint Contract

Any project implementing the frontend emitter template needs a backend endpoint to receive events. The canonical contract:

**POST /api/events**

Request body:
```json
{
 "events": [
 {
 "event_id": "uuid-v4",
 "event_name": "PageViewed",
 "event_kind": "analytics",
 "event_type": "page_view",
 "event_time": "2026-03-12T14:30:00.000Z",
 "event_outcome": "completed",
 "severity": "INFO",
 "source_type": "frontend",
 "duration_ms": null,
 "session_id": "client-session-uuid",
 "user_id": "user-uuid-or-null",
 "org_id": "org-uuid-or-null",
 "context": {}
 }
 ]
}
```

Validation rules:
- `events` array: required, max 50 events per batch
- `event_id`: required, UUID v4 format, used for deduplication (`ON CONFLICT DO NOTHING`)
- `event_name`: required, non-empty string, max 100 characters
- `event_kind`: required, must be one of: `analytics`, `system`, `audit`, `security`, `metric`, `lifecycle`, `workflow`
- `event_time`: required, ISO 8601 UTC
- `source_type`: required, must be one of: `agent`, `backend`, `frontend`, `system`, `script`, `hook`, `skill`
- `severity`: optional, defaults to `INFO`
- `context`: optional, max 64KB total envelope size, max 2KB per context field
- `session_id`: required, non-empty string

Success response (200):
```json
{
 "accepted": 1,
 "duplicates": 0
}
```

Error responses:
- 400: Validation error -- `{"error": "validation_error", "message": "...", "field": "..."}`
- 401: Authentication required -- `{"error": "unauthorized"}`
- 413: Payload too large -- `{"error": "payload_too_large", "max_bytes": 65536}`
- 429: Rate limited -- `{"error": "rate_limited", "retry_after_ms": 1000}`

Authentication: Bearer token in `Authorization` header. Token validation authenticates an actor; project-specific authorization is checked separately through that actor's project role and required permission key.

### Envelope Size Limits

| Limit | Value |
|---|---|
| Total envelope | 64 KB |
| Single context field | 2 KB |
| Stacktrace field | 4 KB (truncated from tail) |

### Consideration: exit_code and tool_name Placement

`exit_code` and `tool_name` are promoted to root-level columns (not context-only) for two reasons:

1. **Query performance.** These fields appear in nearly every agent event and are the primary filter criteria for anomaly detection. Root-level columns avoid JSON parsing on every query.
2. **Cross-source relevance.** While `tool_name` is agent-specific today, backend services may emit tool/function-level telemetry in the future. `exit_code` is universally meaningful for any process-level event.

Both fields remain nullable -- frontend events will have `tool_name = NULL` and `exit_code = NULL`.

---

## Continue Reading

Section A above defines the canonical envelope. The rest of the standard is split into focused sub-pages:

- [Property Group Definitions](structured-logging-standard/property-groups.md) -- field-by-field schemas for `event_props`, `system_props`, `user_props`, `org_props`, `session_props`, `request_props`, `error_props`, `agent_props`, `page_props`, `device_props`, and `marketing_attribution_props`.
- [Full Envelope Composition Per Source Type](structured-logging-standard/source-type-composition.md) -- which property groups are required for `agent`, `backend`, `frontend`, and `system` events.
- [Python Implementation Templates](structured-logging-standard/python-templates.md) -- the `yoke_core.domain.events.emit_event` reference and the standalone `events.py` template.
- [JS/TS Implementation Template](structured-logging-standard/js-ts-template.md) -- the frontend `events.ts` reference module with batching and attribution.
- [Marketing Attribution Template](structured-logging-standard/marketing-attribution.md) -- attribution lifecycle, cookie schema, and `getAttributionProps()` implementation.
- [Agent Session Transcript Pattern](structured-logging-standard/agent-session-pattern.md) -- session reconstruction, canonical SQL queries, and key design decisions.
- [Event Taxonomy, Severity, Correlation, Versioning](structured-logging-standard/taxonomy-appendix.md) -- the appendix covering event taxonomy, severity levels, cross-event correlation, and envelope versioning.
