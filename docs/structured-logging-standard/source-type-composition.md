# Full Envelope Composition Per Source Type

Cross-link back from [structured-logging-standard.md](../structured-logging-standard.md) for the canonical envelope, [property-groups.md](property-groups.md) for the field definitions composed below, and the implementation templates for end-to-end emitter code.

## Source Type: agent

Envelope composition: event_props + system_props + session_props + request_props + agent_props + error_props (on error) + context

Required groups: event_props, system_props, session_props, request_props, agent_props
Conditional groups: error_props (when event_outcome = "failed")
Emission pattern: Hook-emitted (PostToolUse/PostToolUseFailure) or explicit `yoke_core.domain.events.emit_event` calls

```json
{
 "event_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
 "event_name": "HarnessToolCallCompleted",
 "event_kind": "system",
 "event_type": "tool_call",
 "event_time": "2026-03-12T14:30:00.123Z",
 "event_outcome": "completed",
 "severity": "INFO",
 "source_type": "agent",
 "duration_ms": 342,

 "environment": "development",
 "service": "cli",
 "service_version": "1.0.0",
 "project": "yoke",

 "session_id": "claude-session-abc123",
 "trace_id": "dispatch-chain-uuid",
 "parent_id": "parent-event-uuid",
 "request_id": null,

 "agent": "engineer",
 "item_id": "42",
 "task_num": 3,
 "tool_name": "Bash",
 "worktree_path": "/Users/dev/yoke/.worktrees/YOK-N",

 "context": {
 "command": "npm test",
 "exit_code": 0,
 "output_bytes": 4096
 }
}
```

## Source Type: backend

Envelope composition: event_props + system_props + user_props + org_props + session_props + request_props + error_props (on error) + context

Required groups: event_props, system_props, user_props, session_props, request_props
Conditional groups: org_props (when org context exists), error_props (on failure)
Emission pattern: Explicit calls from application code via events.py module

```json
{
 "event_id": "b2c3d479-f47a-c10b-58cc-4372a5670e02",
 "event_name": "OrderCreated",
 "event_kind": "audit",
 "event_type": "order",
 "event_time": "2026-03-12T15:45:00.000Z",
 "event_outcome": "completed",
 "severity": "INFO",
 "source_type": "backend",
 "duration_ms": 89,

 "environment": "production",
 "service": "api",
 "service_version": "2.1.0",
 "project": "buzz",

 "user_id": "usr_a1b2c3d4",
 "user_email": "alice@example.com",
 "user_name": "Alice",
 "is_anonymous": false,

 "org_id": "org_x1y2z3",
 "org_name": "Acme Corp",
 "org_plan": "pro",

 "session_id": "sess_d4e5f6g7",
 "session_start_time": "2026-03-12T15:30:00.000Z",

 "request_id": "req_h8i9j0k1",
 "trace_id": "trace_l2m3n4o5",
 "parent_id": null,

 "context": {
 "order_id": "ord_p6q7r8s9",
 "total_cents": 4999,
 "item_count": 3,
 "payment_method": "stripe"
 }
}
```

## Source Type: frontend

Envelope composition: event_props + system_props + user_props + org_props + session_props + page_props + device_props + marketing_attribution_props (on acquisition) + context

Required groups: event_props, system_props, user_props, session_props, page_props, device_props
Conditional groups: org_props (when org context exists), marketing_attribution_props (on acquisition events)
Emission pattern: Client-side SDK calls, batched to /api/events endpoint

```json
{
 "event_id": "c3d479f4-7ac1-0b58-cc43-72a5670e02b2",
 "event_name": "PageViewed",
 "event_kind": "analytics",
 "event_type": "page_view",
 "event_time": "2026-03-12T16:00:00.000Z",
 "event_outcome": "completed",
 "severity": "INFO",
 "source_type": "frontend",
 "duration_ms": null,

 "environment": "production",
 "service": "web",
 "service_version": "3.0.1",
 "project": "buzz",

 "user_id": "usr_a1b2c3d4",
 "user_email": null,
 "user_name": "Alice",
 "is_anonymous": false,

 "org_id": "org_x1y2z3",
 "org_name": "Acme Corp",
 "org_plan": "pro",

 "session_id": "frontend-sess-uuid",
 "session_start_time": "2026-03-12T15:55:00.000Z",

 "page_url": "https://app.buzz.com/dashboard?tab=orders",
 "page_path": "/dashboard",
 "page_title": "Dashboard - Buzz",
 "referrer": "https://www.google.com/search?q=buzz+app",

 "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
 "browser": "Chrome 120",
 "os": "macOS 14.2",
 "device_type": "desktop",

 "utm_source": "google",
 "utm_medium": "cpc",
 "utm_campaign": "spring-2026",
 "utm_term": "software delivery",
 "utm_content": "ad-variant-a",
 "referrer_domain": "google.com",
 "acquisition_channel": "paid",

 "context": {
 "tab": "orders",
 "items_visible": 25
 }
}
```

## Source Type: system

Envelope composition: event_props + system_props + session_props + error_props (on error) + context

Required groups: event_props, system_props, session_props
Conditional groups: error_props (on failure)
Emission pattern: Explicit `yoke_core.domain.events.emit_event` calls from Python processes (cron jobs, deployment pipelines, maintenance scripts)

```json
{
 "event_id": "d479f47a-c10b-58cc-4372-a5670e02b2c3",
 "event_name": "DatabasePruned",
 "event_kind": "system",
 "event_type": "maintenance",
 "event_time": "2026-03-12T02:00:00.000Z",
 "event_outcome": "completed",
 "severity": "INFO",
 "source_type": "system",
 "duration_ms": 1523,

 "environment": "production",
 "service": "cron",
 "service_version": null,
 "project": "yoke",

 "session_id": "1710208800-12345",

 "context": {
 "table": "events",
 "rows_deleted": 1420,
 "oldest_retained": "2026-02-10T00:00:00.000Z"
 }
}
```

---

