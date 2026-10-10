# Python Implementation Templates

Cross-link back from [structured-logging-standard.md](../structured-logging-standard.md) for the canonical envelope, [property-groups.md](property-groups.md) for the field definitions consumed below, [source-type-composition.md](source-type-composition.md) for per-source-type composition, and [js-ts-template.md](js-ts-template.md) for the frontend (`source_type=frontend`) emitter.

## Template 1: Python Emitter (`yoke_core.domain.events.emit_event`)

The in-process engine emitter. Registered functions own control-plane writes;
this import is a source implementation API, not an alternative agent command.
Hook observation has its own producer in `observe_event_emission.py`.

**Call shape:**

```python
emit_event(
    "HarnessToolCallCompleted",
    event_kind="system",
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
    "DatabasePruned",
    event_kind="system",
    event_type="maintenance",
    source_type="system",
    severity="INFO",
    outcome="completed",
    duration_ms=1523,
    context={"table": "events", "rows_deleted": 1420},
)

emit_event(
    "HarnessToolCallFailed",
    event_kind="system",
    event_type="tool_call",
    source_type="agent",
    severity="ERROR",
    outcome="failed",
    agent="engineer",
    tool_name="Bash",
    exit_code=1,
    anomaly_flags="nonzero_exit",
    context={"command": "npm test", "error_category": "command_failure",
             "error_message": "Command exited with status 1"},
)
```

**Behavior:**

`events.py` generates a UUID v4 and UTC `created_at` unless a timestamp is
provided; the core envelope uses `created_at`, unlike the frontend/Pack
`event_time`. It normalizes severity and bare item identity (numeric text in
JSON, INTEGER in the indexed table). Pass registered session, project,
environment and trusted `auth_context` from the caller; do not fabricate a
session from the clock or PID. Service is `cli`; unset context stays unset.
Active tracing supplies trace/span identity.

String context values are clipped to 2,048 characters. Total-envelope fitting
uses the 65,536-byte bound and preserves identity scalars with per-value
truncation markers. Severity and isolation gates precede insertion. Test
capture writes only its configured capture; HTTPS without an explicit local
connection returns the named transport refusal, while relayed functions emit
server-side. See [event contract](../event-contract.md) for attribution and
capture ownership.

The return is `EmitResult`, not a process exit code. Ordinary emission failures
return a non-ok result with a reason. Retired names raise their dedicated error;
`transactional=True` without `conn` raises `ValueError`. A successful explicit
connection commits by default; transactional emission leaves commit ownership
to the caller. Disposable telemetry does not gate product work.

## Template 2: standalone Python emitter

The executable [Structured Events Pack 4.1.0](../../packs/structured-events/versions/4.1.0/files/events/README.md)
is the standalone Python template. Install events.py, events_props.py,
events_attribution.py, events_cookie.py, events_delivery.py and their shared
attribution_rules.json together. Use build_event/emit_event for backend envelopes;
HTTP emission requires publishable_key, passed to the X-Events-Key header.
The destination below is a consuming project's own ingestion contract; Yoke's
`/api/events` admits only frontend analytics, not this backend audit envelope:

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
