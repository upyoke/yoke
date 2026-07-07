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
3. Resolves `session_id` from: `$CLAUDE_SESSION_ID` > hook JSON payload > `$(date +%s)-$$` fallback
4. Resolves `environment` from `$YOKE_ENV` or defaults to `development`
5. Resolves `project` from `$YOKE_PROJECT` or defaults to `yoke`
6. Checks write-side severity config before inserting (skips if below threshold)
7. Enforces envelope size limits (64KB max, 2KB per context field, 4KB stacktrace)
8. Inserts the built JSON envelope via `yoke_core.domain.events.emit_event`
9. Always exits 0 (graceful degradation)

**Session ID Fallback Chain:**

```
$CLAUDE_SESSION_ID (if set in environment)
 -> hook JSON .session_id (if available from hook payload)
 -> "$(date +%s)-$$" (deterministic fallback for scripts)
```

**System Props Resolution:**

```sh
# Resolved automatically by yoke_core.domain.events.emit_event
environment="${YOKE_ENV:-development}"
service="${SERVICE:-cli}"
service_version="${SERVICE_VERSION:-}"
project="${YOKE_PROJECT:-yoke}"
```

## Template 2: Python Emitter (events.py)

Reference implementation for `backend` source type. Complete module with property group builders and emission.

```python
"""
Structured event emitter -- Python reference implementation.

Usage:
 from events import emit_event, build_event

 emit_event(
 name="OrderCreated",
 kind="audit",
 event_type="order",
 outcome="completed",
 duration_ms=89,
 user_id="usr_a1b2c3d4",
 org_id="org_x1y2z3",
 context={"order_id": "ord_p6q7r8s9", "total_cents": 4999}
 )
"""
import os
import uuid
import time
import json
import traceback
from datetime import datetime, timezone
from typing import Optional, Any

# --- Property Group Builders ---

def get_system_props() -> dict:
 """Resolve system properties from environment."""
 return {
 "environment": os.environ.get("APP_ENV", "development"),
 "service": os.environ.get("SERVICE_NAME", "api"),
 "service_version": os.environ.get("SERVICE_VERSION"),
 "project": os.environ.get("PROJECT", "yoke"),
 }

def get_request_props(
 request_id: Optional[str] = None,
 trace_id: Optional[str] = None,
 parent_id: Optional[str] = None,
) -> dict:
 """Build request correlation properties."""
 return {
 "request_id": request_id or str(uuid.uuid4()),
 "trace_id": trace_id,
 "parent_id": parent_id,
 }

def get_user_props(
 user_id: Optional[str] = None,
 user_email: Optional[str] = None,
 user_name: Optional[str] = None,
 is_anonymous: bool = False,
) -> dict:
 """Build user properties."""
 return {
 "user_id": user_id,
 "user_email": user_email,
 "user_name": user_name,
 "is_anonymous": is_anonymous,
 }

def get_org_props(
 org_id: Optional[str] = None,
 org_name: Optional[str] = None,
 org_plan: Optional[str] = None,
) -> dict:
 """Build organization properties."""
 return {
 "org_id": org_id,
 "org_name": org_name,
 "org_plan": org_plan,
 }

def get_session_props(session_id: Optional[str] = None) -> dict:
 """Build session properties."""
 return {
 "session_id": session_id or str(uuid.uuid4()),
 "session_start_time": None, # Set by caller if known
 }

def get_error_props(
 error: Optional[Exception] = None,
 error_code: Optional[str] = None,
 error_category: str = "unknown",
 is_retryable: bool = False,
) -> dict:
 """Build error properties from an exception or explicit values."""
 if error is None:
 return {}
 return {
 "error_code": error_code,
 "error_category": error_category,
 "error_message": str(error)[:2048], # 2KB limit
 "is_retryable": is_retryable,
 "exception_type": type(error).__name__,
 "stacktrace": traceback.format_exc()[-4096:], # 4KB, truncated from tail
 }

# --- Event Builder ---

def build_event(
 name: str,
 kind: str,
 event_type: str,
 source_type: str = "backend",
 outcome: Optional[str] = None,
 severity: str = "INFO",
 duration_ms: Optional[int] = None,
 event_id: Optional[str] = None,
 event_time: Optional[str] = None,
 context: Optional[dict] = None,
 **extra_props,
) -> dict:
 """
 Build a complete event envelope.

 Extra keyword arguments are merged into the root envelope,
 allowing any property group fields to be passed directly.
 """
 # Enforce context field size limits
 if context:
 for key, value in context.items():
 if isinstance(value, str) and len(value) > 2048:
 context[key] = value[:2048]

 envelope = {
 # event_props
 "event_id": event_id or str(uuid.uuid4()),
 "event_name": name,
 "event_kind": kind,
 "event_type": event_type,
 "event_time": event_time or datetime.now(timezone.utc).isoformat(
 timespec="milliseconds"
 ).replace("+00:00", "Z"),
 "event_outcome": outcome,
 "severity": severity,
 "source_type": source_type,
 "duration_ms": duration_ms,
 # system_props (auto-resolved)
 **get_system_props(),
 # context
 "context": context or {},
 }

 # Merge extra property group fields
 envelope.update(extra_props)

 # Enforce total envelope size
 encoded = json.dumps(envelope)
 if len(encoded) > 65536:
 # Truncate context to fit
 envelope["context"] = {"_truncated": True}

 return envelope

# --- Emitter ---

def emit_event(
 name: str,
 kind: str,
 event_type: str,
 destination: str = "stdout",
 **kwargs,
) -> dict:
 """
 Build and emit an event.

 Args:
 name: PascalCase event name (e.g., "OrderCreated")
 kind: Event kind enum (analytics, system, audit, security, metric)
 event_type: Project-specific type string
 destination: "stdout" (default), "file:/path", or "http://endpoint"
 **kwargs: Passed to build_event (includes all property group fields)

 Returns:
 The emitted event envelope.
 """
 event = build_event(name=name, kind=kind, event_type=event_type, **kwargs)

 if destination == "stdout":
 print(json.dumps(event))
 elif destination.startswith("file:"):
 path = destination[5:]
 with open(path, "a") as f:
 f.write(json.dumps(event) + "\n")
 elif destination.startswith("http"):
 import urllib.request
 req = urllib.request.Request(
 destination,
 data=json.dumps({"events": [event]}).encode(),
 headers={"Content-Type": "application/json"},
 method="POST",
 )
 try:
 urllib.request.urlopen(req, timeout=5)
 except Exception:
 pass # Graceful degradation -- never crash on emit failure

 return event
```
