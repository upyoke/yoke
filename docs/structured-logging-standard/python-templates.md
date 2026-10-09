# Python Implementation Templates

Cross-link back from [structured-logging-standard.md](../structured-logging-standard.md) for the canonical envelope, [property-groups.md](property-groups.md) for the field definitions consumed below, [source-type-composition.md](source-type-composition.md) for per-source-type composition, and [js-ts-template.md](js-ts-template.md) for the frontend (`source_type=frontend`) emitter.

## Template 1: Python Emitter (`yoke_core.domain.events.emit_event`)

The canonical Python emitter for `agent` and `system` source types. All Yoke scripts and hooks use this as the single entry point for event emission.

**Call shape:**

```python
emit_event(
    name="HarnessToolCallCompleted",
    kind="system",
    event_type="tool_call",
    source_type="agent",
    severity="INFO",
    outcome="completed",
    agent="engineer",
    tool_name="Bash",
    duration_ms=342,
    item_id=42,
    task_num=3,
    context={"command": "npm test", "exit_code": 0},
)

# Pass bare numeric `item_id` values to the emitter; stored `events.item_id` remains `42`.

emit_event(
    name="DatabasePruned",
    kind="system",
    event_type="maintenance",
    source_type="system",
    severity="INFO",
    outcome="completed",
    duration_ms=1523,
    context={"table": "events", "rows_deleted": 1420},
)

emit_event(
    name="HarnessToolCallFailed",
    kind="system",
    event_type="tool_call",
    source_type="agent",
    severity="ERROR",
    outcome="failed",
    agent="engineer",
    tool_name="Bash",
    exit_code=1,
    error_category="command_failure",
    error_message="Command exited with status 1",
    anomaly_flags=["nonzero_exit"],
    context={"command": "npm test", "exit_code": 1},
)
```

**Behavior:**

1. Generates `event_id` (UUID v4) if not provided via `--event-id`
2. Sets `event_time` to current UTC if not provided
3. Resolves `session_id` from: `$CLAUDE_CODE_SESSION_ID` > hook JSON payload > `$(date +%s)-$$` fallback
4. Resolves `environment` from `$YOKE_ENV` or defaults to `development`
5. Resolves `project` from explicit caller context, `$YOKE_PROJECT`, or caller checkout binding; unresolved telemetry stays unattributed
6. Checks write-side severity config before inserting (skips if below threshold)
7. Enforces envelope size limits (64KB max, 2KB per context field, 4KB stacktrace)
8. Inserts the built JSON envelope via `yoke_core.domain.events.emit_event`
9. Always exits 0 (graceful degradation)

**Session ID Fallback Chain:**

```
$CLAUDE_CODE_SESSION_ID (if set in environment)
 -> hook JSON .session_id (if available from hook payload)
 -> "$(date +%s)-$$" (deterministic fallback for scripts)
```

**System Props Resolution:**

```sh
# Resolved automatically by yoke_core.domain.events.emit_event
environment="${YOKE_ENV:-development}"
service="${SERVICE:-cli}"
service_version="${SERVICE_VERSION:-}"
project="${YOKE_PROJECT:-}"
```

## Template 2: standalone Python emitter

The executable [Structured Events Pack 4.1.0](../../packs/structured-events/versions/4.1.0/files/events/README.md)
is the standalone Python template. Install events.py, events_props.py,
events_attribution.py, events_cookie.py, events_delivery.py and their shared
attribution_rules.json together. Use build_event/emit_event for backend envelopes;
HTTP emission requires publishable_key, passed to the X-Events-Key header:

```python
emit_event("OrderCreated", "audit", "order", destination="https://example.com/api/events",
           publishable_key="project-public-routing-key")
# For explicit batching: EventBatch(endpoint, publishable_key, transport=transport).
# The process schedules flush after retry_at.
```

A missing key reports publishable_key_required. Failures never gate product work.

## Attribution and delivery in the standalone Pack

[Structured Events Pack 4.1.0](../../packs/structured-events/versions/4.1.0/files/events/README.md)
provides events_attribution.py and AttributionCookie in events_cookie.py with
shared rules and the same signed server-cookie shape as TypeScript. Routes
capture and return Set-Cookie. get_attribution_props(record) attaches
visitor_id and both touches, or an empty group when there is no record.
Required signup facts belong to
the account owner. sanitize_url and is_bot share the browser's privacy/bot rules.
EventBatch retries only network failures, 429 and 5xx with batch_requeued;
429 honors Retry-After. Other HTTP refusals discard the batch and report
batch_refused with the collector's error and recovery. The queue holds at most
500 pending events: append discards the oldest; requeue retains retry ids and
discards the newest overflow. The process schedules flush after retry_at.
Invalid or rotated cookie signatures report attribution_cookie_reminted and
the next capture replaces the old identity using the current signing secret.
The canonical engine emitter above is project-owned; Pack adoption is a separate
integration. Disposable telemetry never gates product work.
