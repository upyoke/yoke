"""Tests for the Python event emitter — emission paths + integration.

Companion to ``test_events.py`` (which keeps the property-builder and
``build_event`` coverage). Validates:

- emit_event returns the built envelope
- emit_event_obj handles destinations
- Graceful degradation on emit failure
- Complete UserLoggedIn example produces a valid envelope
- build_event does not mutate the caller's context dict
"""
import json
import os
import sys
import tempfile
import uuid

# Add parent directory to path for import
sys.path.insert(0, os.path.dirname(__file__))
from events import (
    build_event,
    emit_event,
    emit_event_obj,
    get_org_props,
    get_request_props,
    get_session_props,
    get_system_props,
    get_actor_props,
)


def test_emit_event_returns_envelope():
    """emit_event returns the built event envelope."""
    for var in ("APP_ENV", "SERVICE_NAME", "SERVICE_VERSION", "PROJECT"):
        os.environ.pop(var, None)

    event = emit_event(
        name="Test",
        kind="system",
        event_type="test",
        destination="file:/dev/null",
    )
    assert event["event_name"] == "Test"
    assert "event_id" in event


def test_emit_event_file_destination():
    """emit_event writes JSON line to file destination."""
    with tempfile.NamedTemporaryFile(mode="r", suffix=".jsonl", delete=False) as f:
        path = f.name

    try:
        emit_event(
            name="FileTest",
            kind="system",
            event_type="test",
            destination=f"file:{path}",
        )

        with open(path) as f:
            line = f.readline()
        data = json.loads(line)
        assert data["event_name"] == "FileTest"
    finally:
        os.unlink(path)


def test_emit_event_obj_stdout(capsys):
    """emit_event_obj prints JSON to stdout."""
    event = build_event(name="StdoutTest", kind="system", event_type="test")
    emit_event_obj(event, destination="stdout")
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["event_name"] == "StdoutTest"


def test_emit_event_graceful_degradation():
    """Emitting to a bad HTTP endpoint does not raise."""
    # This should not raise even though the endpoint is unreachable
    event = emit_event(
        name="Test",
        kind="system",
        event_type="test",
        destination="http://localhost:1/nonexistent",
    )
    assert event["event_name"] == "Test"


def test_emit_event_obj_graceful_degradation():
    """emit_event_obj does not raise on bad destination."""
    event = build_event(name="Test", kind="system", event_type="test")
    # Should not raise
    emit_event_obj(event, destination="http://localhost:1/nonexistent")


def test_complete_user_logged_in_example():
    """
    Complete example: UserLoggedIn audit event with all property groups.
    Validates the canonical envelope structure from the standard.
    """
    for var in ("APP_ENV", "SERVICE_NAME", "SERVICE_VERSION", "PROJECT"):
        os.environ.pop(var, None)

    system = get_system_props(service="api", project="buzz")
    actor = get_actor_props(actor_id=17)
    org = get_org_props(
        org_id="org_x1y2z3", org_name="Acme Corp", org_plan="pro"
    )
    session = get_session_props(
        session_id="sess_d4e5f6g7",
        session_start_time="2026-03-12T15:30:00.000Z",
    )
    request = get_request_props(
        request_id="req_h8i9j0k1",
        trace_id="trace_l2m3n4o5",
    )

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
        },
        **system,
        **actor,
        **org,
        **session,
        **request,
    )

    # Verify all canonical envelope fields present
    assert event["event_name"] == "UserLoggedIn"
    assert event["event_kind"] == "audit"
    assert event["event_type"] == "auth"
    assert event["event_outcome"] == "completed"
    assert event["severity"] == "INFO"
    assert event["source_type"] == "backend"
    assert event["duration_ms"] == 142
    assert event["event_time"].endswith("Z")
    uuid.UUID(event["event_id"])

    # system_props
    assert event["environment"] == "development"
    assert event["service"] == "api"
    assert event["project"] == "buzz"

    # actor_props
    assert event["actor_id"] == 17
    assert "user_id" not in event
    assert event["is_anonymous"] is False

    # org_props
    assert event["org_id"] == "org_x1y2z3"
    assert event["org_name"] == "Acme Corp"
    assert event["org_plan"] == "pro"

    # session_props
    assert event["session_id"] == "sess_d4e5f6g7"
    assert event["session_start_time"] == "2026-03-12T15:30:00.000Z"

    # request_props
    assert event["request_id"] == "req_h8i9j0k1"
    assert event["trace_id"] == "trace_l2m3n4o5"
    assert event["parent_id"] is None

    # context
    assert event["context"]["login_method"] == "oauth"
    assert event["context"]["provider"] == "google"

    # Verify it serializes cleanly
    serialized = json.dumps(event)
    roundtrip = json.loads(serialized)
    assert roundtrip == event


def test_context_not_mutated():
    """build_event does not mutate the caller's context dict."""
    ctx = {"field": "a" * 5000}
    original_len = len(ctx["field"])

    build_event(name="Test", kind="system", event_type="test", context=ctx)

    assert len(ctx["field"]) == original_len


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
