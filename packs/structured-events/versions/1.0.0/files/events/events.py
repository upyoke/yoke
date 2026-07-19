"""
Structured event emitter -- Python reference implementation.

Implements a canonical event envelope for backend event emission. This
installed source is intended to be adapted to the project's event pipeline.

Property group builders resolve fields from explicit arguments, with
environment-variable fallbacks for system props.

The reference splits across two sibling files. Copy BOTH into your project
together: events_props.py and this file (events.py). See
events/README.md for details.

Usage:
    from events import emit_event, build_event

    # Simple emit -- builds and emits in one call
    emit_event(
        name="OrderCreated",
        kind="audit",
        event_type="order",
        outcome="completed",
        duration_ms=89,
        actor_id=17,
        org_id="org_x1y2z3",
        context={"order_id": "ord_p6q7r8s9", "total_cents": 4999}
    )

    # Composable style -- build prop groups, then assemble
    system = get_system_props(service="api", project="myproject")
    actor = get_actor_props(actor_id=17)
    org = get_org_props(org_id="org_x1y2z3", org_name="Acme Corp", org_plan="pro")
    request = get_request_props(request_id="req_h8i9j0k1")

    event = build_event(
        name="UserLoggedIn",
        kind="audit",
        event_type="auth",
        outcome="completed",
        context={"login_method": "oauth", "provider": "google"},
        **system, **actor, **org, **request,
    )
    emit_event_obj(event)
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Size limits (from standard spec)
# ---------------------------------------------------------------------------
MAX_ENVELOPE_BYTES = 65536       # 64 KB total envelope
MAX_CONTEXT_FIELD_BYTES = 2048   # 2 KB per context string field
MAX_STACKTRACE_BYTES = 4096      # 4 KB stacktrace


# ---------------------------------------------------------------------------
# Property group builders -- defined in the sibling events_props.py module.
# Re-exported here so existing `from events import get_*_props` callers keep
# working without modification when both files are co-located on sys.path.
# ---------------------------------------------------------------------------
from events_props import (  # noqa: E402
    get_org_props,
    get_request_props,
    get_session_props,
    get_system_props,
    get_actor_props,
)


# ---------------------------------------------------------------------------
# Event Builder
# ---------------------------------------------------------------------------

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
    **extra_props: Any,
) -> dict:
    """
    Build a complete event envelope.

    Merges event_props (generated here) with any extra keyword arguments,
    which should come from property group builders. System props are
    auto-resolved if not provided via extra_props.

    Args:
        name: PascalCase event name (e.g., "UserLoggedIn")
        kind: Event kind enum (analytics, system, audit, security, metric)
        event_type: Domain-specific type string (e.g., "auth", "order")
        source_type: Source type enum (agent, backend, frontend, system)
        outcome: Event outcome (completed, failed, skipped, or None)
        severity: Log severity (DEBUG, INFO, WARN, ERROR, FATAL)
        duration_ms: Operation duration in milliseconds
        event_id: Pre-generated UUID (auto-generated if omitted)
        event_time: ISO 8601 timestamp (auto-generated if omitted)
        context: Event-specific payload dict
        **extra_props: Fields from property group builders, merged at root

    Returns:
        Complete event envelope dict matching the canonical schema.
    """
    # Enforce context field size limits
    safe_context = dict(context) if context else {}
    for key, value in safe_context.items():
        if isinstance(value, str) and len(value) > MAX_CONTEXT_FIELD_BYTES:
            safe_context[key] = value[:MAX_CONTEXT_FIELD_BYTES]

    # Build timestamp in ISO 8601 UTC with Z suffix
    if event_time is None:
        event_time = (
            datetime.now(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
            + "Z"
        )

    envelope = {
        # event_props
        "event_id": event_id or str(uuid.uuid4()),
        "event_name": name,
        "event_kind": kind,
        "event_type": event_type,
        "event_time": event_time,
        "event_outcome": outcome,
        "severity": severity,
        "source_type": source_type,
        "duration_ms": duration_ms,
        # system_props (auto-resolved as defaults)
        **get_system_props(),
        # context
        "context": safe_context,
    }

    # Merge extra property group fields (overrides system_props if provided)
    envelope.update(extra_props)

    # Enforce total envelope size (64 KB)
    encoded = json.dumps(envelope)
    if len(encoded) > MAX_ENVELOPE_BYTES:
        envelope["context"] = {"_truncated": True}

    return envelope


# ---------------------------------------------------------------------------
# Emitters
# ---------------------------------------------------------------------------

def emit_event_obj(
    event: dict,
    destination: str = "stdout",
) -> None:
    """
    Emit a pre-built event envelope.

    Args:
        event: Complete event envelope from build_event().
        destination: "stdout" (default), "file:/path", or "http://endpoint"

    Never raises -- emitter failures are silently swallowed (graceful
    degradation principle from the standard).
    """
    try:
        _emit(event, destination)
    except Exception:
        pass  # Graceful degradation -- never crash on emit failure


def emit_event(
    name: str,
    kind: str,
    event_type: str,
    destination: str = "stdout",
    **kwargs: Any,
) -> dict:
    """
    Build and emit an event in one call.

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

    try:
        _emit(event, destination)
    except Exception:
        pass  # Graceful degradation

    return event


def _emit(event: dict, destination: str) -> None:
    """Internal dispatch to the configured destination."""
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
        urllib.request.urlopen(req, timeout=5)


# ---------------------------------------------------------------------------
# Complete Example: UserLoggedIn audit event with all prop groups
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Compose all property groups explicitly
    system = get_system_props(service="api", project="myproject")
    actor = get_actor_props(actor_id=17)
    org = get_org_props(
        org_id="org_x1y2z3",
        org_name="Acme Corp",
        org_plan="pro",
    )
    session = get_session_props(
        session_id="sess_d4e5f6g7",
        session_start_time="2026-03-12T15:30:00.000Z",
    )
    request = get_request_props(
        request_id="req_h8i9j0k1",
        trace_id="trace_l2m3n4o5",
    )

    # Build the event with all groups merged
    event = build_event(
        name="UserLoggedIn",
        kind="audit",
        event_type="auth",
        outcome="completed",
        severity="INFO",
        duration_ms=142,
        context={
            "login_method": "oauth",
            "provider": "google",
            "ip_address": "203.0.113.42",
            "user_agent": "Mozilla/5.0",
        },
        **system,
        **actor,
        **org,
        **session,
        **request,
    )

    # Emit to stdout (pretty-printed for readability)
    print(json.dumps(event, indent=2))
