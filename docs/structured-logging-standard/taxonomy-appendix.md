## Appendix: Event Taxonomy, Severity, Correlation, Versioning

### Event Taxonomy

**Event Kind Enum:**

| Kind | Description | Examples |
|---|---|---|
| `analytics` | User behavior and product usage | PageViewed, ButtonClicked, FeatureUsed |
| `system` | Runtime, harness, and operational events | HarnessToolCallStarted, HarnessToolCallCompleted, DatabasePruned, HarnessSessionStarted |
| `audit` | Reviewable policy and guardrail decisions | HarnessToolCallDenied, PermissionChanged, UserDeleted |
| `security` | Authentication and authorization events | LoginAttempted, TokenRevoked, AccessDenied |
| `metric` | Numeric measurements and gauges | LatencyMeasured, QueueDepthRecorded |
| `lifecycle` | State machine transitions | TaskStatusChanged, ItemStatusChanged |
| `workflow` | Orchestration milestones | VerdictRendered, DeploymentStarted, FrontierComputed |

`event_kind` is the semantic class of the event. Emitter/source identity belongs in `source_type`, `service`, and registry ownership metadata.

**Event Name Convention:**

- PascalCase, always
- Verb-first (past participle): `Started`, `Completed`, `Failed`, `Created`, `Updated`, `Deleted`, `Approved`, `Revised`, `Viewed`, `Clicked`, `Submitted`
- Examples: `PageViewed`, `OrderCreated`, `HarnessToolCallFailed`, `HarnessSessionSentFirstUserPromptSubmit`

**Event Type:**

- Project-specific free string for sub-categorization
- Lowercase with underscores: `page_view`, `tool_call`, `api_request`, `order`, `session_lifecycle`
- Used for grouping related events: `SELECT * FROM events WHERE event_type = 'tool_call'`

### Severity Definitions

| Severity | When to Use | Retention Guidance |
|---|---|---|
| `DEBUG` | Verbose diagnostic information. Tool call details, intermediate state. On-demand-capture tier: dropped at the default INFO write floor, enabled by lowering `severity_config` to DEBUG. | 1 day |
| `INFO` | Normal operational events. Successful completions, state transitions. | 30 days |
| `WARN` | Unexpected but recoverable conditions. Anomalies, retries, degraded performance. | 90 days |
| `ERROR` | Failed operations that need attention. Tool failures, unhandled exceptions. | Forever |
| `FATAL` | Unrecoverable failures that stop execution. Session crashes, data corruption. | Forever |

Write-side severity configuration allows filtering at emission time. The `severity_config` table controls which events are actually written to the `events` table.

### Correlation Strategy

Correlation IDs live at the envelope root via session_props and request_props groups:

| Field | Scope | Example |
|---|---|---|
| `session_id` | **Required.** Ties all events in a single agent/user session. | Claude session ID, frontend session UUID |
| `request_id` | Optional. Unique per API request. | Auto-generated per HTTP request |
| `trace_id` | Optional. Spans a user journey across services. | Propagated via `X-Trace-Id` header |
| `parent_id` | Optional. Causality chain -- links to the parent event. | Dispatch chain: parent session emits child session ID |

**Propagation:**

- Frontend to backend: `trace_id` sent as `X-Trace-Id` header
- Backend service to service: `trace_id` + `parent_id` propagated in headers
- Agent dispatch chain: parent `session_id` stored as `parent_id` in child session events

### Context Field Definition

The `context` object holds event-specific payload data -- the details unique to this event type that are not universally queryable.

**Rules:**
- Universal/reusable dimensions live in property groups at the envelope root
- Event-specific details live in `context`
- Consumers can filter and aggregate on root-level fields without parsing `context`
- `context` is a flat or shallow-nested JSON object (avoid deep nesting)
- Each `context` field value is limited to 2KB
- Total `context` size contributes to the 64KB envelope limit

**Examples of context vs root:**

| Field | Placement | Reason |
|---|---|---|
| `tool_name` | Root | Universal query dimension for agent events |
| `command` | Context | Specific to Bash tool calls |
| `file_path` | Context | Specific to Read/Write/Edit tool calls |
| `user_id` | Root | Universal query dimension across source types |
| `order_id` | Context | Specific to order events |

### Backward Compatibility Principle

Structured events MUST be emitted alongside existing logging, never replacing atomically. Migration is additive:

1. Add structured event emission to a code path
2. Verify events are correctly captured
3. Build consumers that read from the events table
4. Only after consumers are stable, consider deprecating legacy logging
5. Never remove legacy logging until all consumers have migrated

### Per-Event-Type Versioning Convention

Context schemas evolve over time. Rules:

1. **Additive only.** New fields can be added to `context` at any time.
2. **Never rename fields.** If a field name was wrong, add the correct name and deprecate (but do not remove) the old one.
3. **Never remove fields.** Old events in the table still have the old schema.
4. **Consumers must tolerate missing fields.** Any field in `context` may be absent on older events.
5. **No explicit version number.** The presence or absence of fields is the version signal. This avoids version-checking boilerplate in consumers.

### Implementation Checklist

Every project adopting this standard MUST define:

- [ ] **Event catalog.** List of all event names, their kinds, types, and context schemas.
- [ ] **Correlation IDs.** How `session_id`, `trace_id`, and `request_id` are generated and propagated.
- [ ] **Context blocks.** Per-event-type context field definitions.
- [ ] **Destinations.** Where events are stored (Postgres, API endpoint, log aggregator).
- [ ] **Sampling policy.** Which events are always captured vs sampled (e.g., 100% for errors, 10% for page views).
- [ ] **Retention policy.** Per-severity retention durations (see severity definitions above for defaults).

### Health Check Integration Points (design only)

Two health checks are designed for the Doctor integration (built in a follow-on epic):

**HC-anomaly-rate:** Alert when the anomaly rate exceeds a threshold over a rolling window.
```sql
SELECT
 COUNT(*) AS anomaly_count,
 (SELECT COUNT(*) FROM events WHERE created_at >= :window_start) AS total_count
FROM events
WHERE anomaly_flags IS NOT NULL
 AND anomaly_flags <> ''
 AND created_at >= :window_start;
-- Alert if anomaly_count / total_count > 0.05 (5%)
```

**HC-event-gap:** Alert when no events have been recorded for longer than expected.
```sql
SELECT MAX(created_at) AS last_event
FROM events
WHERE source_type = 'agent';
-- Alert if last_event is more than 24 hours ago during active work
```
