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

 "environment": "prod",
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

Anomaly flags are stored as a comma-separated TEXT field: `"nonzero_exit,retry_loop"`. Query with `anomaly_flags LIKE '%nonzero_exit%'` or use `yoke events anomalies` for structured access.

### Root-Level Query Columns

For query performance, the following fields are promoted from `context` to root-level columns in the `events` table:

- `tool_name` (TEXT) -- the tool invoked (Bash, Read, Write, Edit, Grep, Glob, Agent)
- `exit_code` (INTEGER) -- tool exit code (null for non-Bash tools)
- `agent` (TEXT) -- the agent that emitted the event
- `item_id` (TEXT) -- backlog item ID (canonical bare-numeric text; display may render `YOK-N`)
- `task_num` (INTEGER) -- epic task number
- `actor_id` (INTEGER) -- authenticated engine actor
- `org_id` (TEXT) -- organization identifier
- `tool_use_id` (TEXT) -- harness-provided tool call ID (dedup key, indexed)
- `turn_id` (TEXT) -- conversation turn within the harness session
- `hook_event_name` (TEXT) -- hook phase that produced this event (`PreToolUse`, `PostToolUse`, `PostToolUseFailure`)

### /api/events Endpoint Contract

The frontend emitter template posts to a collector at `/api/events`. Two
implementations serve the same contract: the engine collector
(`packages/yoke-core/src/yoke_core/api/routes/frontend_events.py`, served by
every Yoke API and workbench) and the Pack reference collector
(`createCollector` in the structured-events Pack's `events/api-route.ts`). The
contract is the HTTP status plus the `error` name; `recovery` text is advice
and differs between the two implementations. Limits come from
`attribution_rules.json` `limits`. The [Pack collector
contract](../packs/structured-events/versions/4.3.0/files/events/README.md)
covers consuming-project wiring, delivery retries and attribution.

**GET /api/events/config** returns `{"publishableKey": "..."}` with
`Cache-Control: no-store`.

**POST /api/events**

Request headers: `Origin` exactly equal to the serving origin (engine) or one
of the configured `allowedOrigins` (Pack); `X-Events-Key` equal to the
publishable key; `Content-Type: application/json`. No bearer token is required.

Request body:
```json
{
  "events": [
    {
      "event_id": "uuid",
      "event_name": "PageViewed",
      "event_kind": "analytics",
      "event_type": "page_view",
      "event_time": "2026-03-12T14:30:00.000Z",
      "source_type": "frontend",
      "session_id": "client-session-uuid",
      "page_url": "https://app.example.com/items",
      "referrer": null,
      "context": {}
    }
  ]
}
```

Admission rules (both collectors):
- `events`: an array of 1..50 envelopes (`limits.batch_size`).
- `event_id`, `event_name`, `event_kind`, `event_type`, `event_time`,
  `session_id`: required non-empty strings. The engine also requires
  `event_id` to parse as a UUID; `event_time` must parse as an ISO 8601
  timestamp, and requires non-empty `service` and `project` strings, which it
  stores as sent (the row still indexes as global, never as that project).
- `source_type` must be `frontend` and `event_kind` must be `analytics`;
  this route never admits backend, audit or security events.
- `page_url`, `referrer` and `page_path`: string or `null`; all three are
  sanitized server-side from the same `attribution_rules.json` the browser
  uses. Sensitive query keys (such as `token` and the device-login
  `user_code`), userinfo and fragments are stripped, and
  `/machine-approval/<code>` is stored as `/machine-approval/redacted`.
- Each envelope at most 64 KB serialized (`limits.envelope_bytes`); the whole
  request at most 512 KB (`limits.request_bytes`).
- Identity is stamped server-side: client `org_id` and `actor_id` are ignored.
  The engine stamps the collector org, its serving environment
  (`YOKE_ENVIRONMENT`) and, when a web-session cookie, a verified
  `Authorization` bearer, or the Local view's per-run token is present, the
  viewer's actor; otherwise the event is anonymous and carries only its
  `visitor_id`.
- Dedupe is silent: a repeated `event_id` is dropped by the sink
  (`ON CONFLICT (event_id) DO NOTHING`) and still counts as accepted.

The 100-character `event_name` limit and the 2 KB per-context-field limit are
emitter-side shrinking rules, not collector refusals.

Success response (200), where `accepted` is the number of envelopes submitted:
```json
{"accepted": 1}
```

Refusals share one shape, `{"error": "<name>", "recovery": "<next step>"}`:

| Status | `error` | Cause |
|---|---|---|
| 400 | `collector_https_required` | Engine only: a non-loopback collector served over plain HTTP. |
| 403 | `origin_not_allowed` | `Origin` missing or not the allowed origin. |
| 401 | `publishable_key_invalid` | `X-Events-Key` missing or wrong. |
| 429 | `rate_limited` | Client exceeded the shared rate budget. `Retry-After` carries whole seconds (engine: the rest of its 60-second window). Retry the same event ids. |
| 400 | `content_type_invalid` | Body is not `application/json`. |
| 413 | `payload_too_large` | Request exceeds 512 KB. |
| 400 | `json_invalid` | Body is not valid JSON. |
| 400 | `events_invalid` | `events` missing, empty, or longer than 50. |
| 400 | `envelope_invalid` | An envelope fails the admission rules above. |
| 413 | `event_too_large` | One envelope exceeds 64 KB. |
| 503 | `collector_unavailable` | Rate limiter or event sink failed; nothing was accepted. Retry the same event ids. |
| 405 | `method_not_allowed` | Pack collector only: a method other than POST. |

On the engine collector, a request that carries an `Authorization` header which
fails verification is refused with the engine auth envelope instead:
401, `WWW-Authenticate: Bearer`, body
`{"success": false, "error": {"code": "...", "message": "..."}}`.

Yoke defines no authenticated HTTP ingestion route for backend, audit or
security events. Those events are written in-process through `emit_event` and
registered functions (see [Python Implementation
Templates](structured-logging-standard/python-templates.md)); a consuming
project that exposes its own authenticated ingestion owns that contract.

Frontend emission and attribution capture run from first load with no consent
state, so collect only non-personal data. Every frontend event attaches
attribution when capture succeeds. `PageViewed` follows the path: a single-page
app emits one view per path change, and a query-only or fragment-only change
(filters, the app's own URL rewrites) emits none. Required signup facts belong
to the durable account/actor owner, never only to events.
Each sign-in links the browser's visitor_id to its actor; page views join to
actors through that link list at query time ([Section E](structured-logging-standard/marketing-attribution.md#visitor-links-tying-page-views-to-actors)).

**Frontend event time.** The collector stamps each accepted frontend event
with its own receipt time: `created_at` is the server receipt time, so ordering
and time-based reports never trust a browser clock. The envelope keeps the
client `event_time` as the client's claim beside `received_at` and
`client_time_offset_seconds` (`event_time` minus receipt; negative when the
event was queued or the client clock runs behind). Beyond 300 seconds either
way the row carries `anomaly_flags = 'client_time_skew'`; it is still accepted.
Rows written before receipt stamping keep `created_at = event_time`.

**Collector refusals.** Every refusal from `/api/events`, `/api/events/config`,
`/api/events/attribution` and its hand-off routes (for example
`origin_not_allowed`, `publishable_key_invalid`, `rate_limited`,
`payload_too_large`, `attribution_handoff_replayed`) also writes one
`FrontendCollectorRefused` event (`source_type = 'backend'`,
`event_kind = 'system'`, severity WARN, `event_outcome` = the reason) with
`context.detail` holding reason, status, route, the truncated Origin and the
serving host — never a request body, cookie, key or client address. At most one
row per reason, status and route per minute is written, so a flood cannot grow
`events` without bound; repeats inside that minute are not counted. The record
is disposable diagnostics: nothing operational reads it, and a failed write
logs `collector_refusal_record_failed` while the caller still receives its
refusal. Each install records its own refusals in its own `events` table.
Collector rows belong to the organization, not a project (`project_id` is
NULL), so project-scoped `yoke events query` does not return them; read recent
refusals with the read-only diagnostic surface:

```bash
yoke db read "SELECT created_at, event_outcome, envelope::jsonb -> 'context' -> 'detail' AS detail FROM events WHERE event_name = 'FrontendCollectorRefused' ORDER BY created_at DESC LIMIT 20"
```

### Envelope Size Limits

| Limit | Value | Enforced by |
|---|---|---|
| Request body | 512 KB | Collector (`payload_too_large`) |
| Events per request | 50 | Collector (`events_invalid`) |
| Total envelope | 64 KB | Collector (`event_too_large`) |
| Single context field | 2 KB | Emitter (shrunk before send) |
| Stacktrace field | 4 KB (truncated from tail) | Emitter |

### Consideration: exit_code and tool_name Placement

`exit_code` and `tool_name` are promoted to root-level columns (not context-only) for these reasons:

1. **Query performance.** These fields appear in nearly every agent event and are the primary filter criteria for anomaly detection. Root-level columns avoid JSON parsing on every query.
2. **Cross-source relevance.** While `tool_name` is agent-specific today, backend services may emit tool/function-level telemetry in the future. `exit_code` is universally meaningful for any process-level event.

Both fields remain nullable -- frontend events will have `tool_name = NULL` and `exit_code = NULL`.

---

## Continue Reading

Section A above defines the canonical envelope. The rest of the standard is split into focused sub-pages:

- [Property Group Definitions](structured-logging-standard/property-groups.md) -- field-by-field schemas for `event_props`, `system_props`, `actor_props`, `org_props`, `session_props`, `request_props`, `error_props`, `agent_props`, `page_props`, `device_props`, and `marketing_attribution_props`.
- [Full Envelope Composition Per Source Type](structured-logging-standard/source-type-composition.md) -- which property groups are required for `agent`, `backend`, `frontend`, and `system` events.
- [Python Implementation Templates](structured-logging-standard/python-templates.md) -- the `yoke_core.domain.events.emit_event` reference and the standalone `events.py` template.
- [JS/TS Implementation Template](structured-logging-standard/js-ts-template.md) -- the frontend `events.ts` reference module with batching and attribution.
- [Marketing Attribution Template](structured-logging-standard/marketing-attribution.md) -- persistent visitor identity, first/last-touch and server storage.
- [Agent Session Transcript Pattern](structured-logging-standard/agent-session-pattern.md) -- session reconstruction, canonical SQL queries, and key design decisions.
- [Event Taxonomy, Severity, Correlation, Versioning](structured-logging-standard/taxonomy-appendix.md) -- the appendix covering event taxonomy, severity levels, cross-event correlation, and envelope versioning.
