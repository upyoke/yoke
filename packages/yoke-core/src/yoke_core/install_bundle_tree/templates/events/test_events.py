"""Tests for the Python event emitter — property builders + build_event.

Companion file ``test_events_emit.py`` covers ``emit_event`` /
``emit_event_obj``, the complete UserLoggedIn example, and
context-mutation safety.

Validates:
- All property group builders return correct fields
- build_event produces canonical envelope structure
- Envelope size limits are enforced
- Context field truncation works
"""
import os
import sys
import uuid

# Add parent directory to path for import
sys.path.insert(0, os.path.dirname(__file__))
from events import (
    build_event,
    get_error_props,
    get_org_props,
    get_request_props,
    get_session_props,
    get_system_props,
    get_actor_props,
)


def test_get_system_props_defaults():
    """System props resolve from env vars with defaults."""
    # Clear env vars to test defaults
    for var in ("APP_ENV", "SERVICE_NAME", "SERVICE_VERSION", "PROJECT"):
        os.environ.pop(var, None)

    props = get_system_props()
    assert props["environment"] == "development"
    assert props["service"] == "api"
    assert props["service_version"] is None
    assert props["project"] == "yoke"


def test_get_system_props_explicit():
    """Explicit arguments override env vars."""
    os.environ["APP_ENV"] = "production"
    os.environ["SERVICE_NAME"] = "worker"

    props = get_system_props(service="api", project="buzz")
    assert props["service"] == "api"
    assert props["project"] == "buzz"
    # Env var used when no explicit arg
    assert props["environment"] == "production"

    # Clean up
    os.environ.pop("APP_ENV", None)
    os.environ.pop("SERVICE_NAME", None)


def test_get_system_props_env_override():
    """Env vars are used when no explicit args provided."""
    os.environ["APP_ENV"] = "staging"
    os.environ["SERVICE_NAME"] = "worker"
    os.environ["SERVICE_VERSION"] = "1.2.3"
    os.environ["PROJECT"] = "buzz"

    props = get_system_props()
    assert props["environment"] == "staging"
    assert props["service"] == "worker"
    assert props["service_version"] == "1.2.3"
    assert props["project"] == "buzz"

    for var in ("APP_ENV", "SERVICE_NAME", "SERVICE_VERSION", "PROJECT"):
        os.environ.pop(var, None)


def test_get_request_props():
    """Request props include correlation IDs."""
    props = get_request_props(
        request_id="req_123", trace_id="trace_456", parent_id="parent_789"
    )
    assert props["request_id"] == "req_123"
    assert props["trace_id"] == "trace_456"
    assert props["parent_id"] == "parent_789"


def test_get_request_props_auto_id():
    """Request ID is auto-generated when not provided."""
    props = get_request_props()
    assert props["request_id"] is not None
    # Should be a valid UUID
    uuid.UUID(props["request_id"])


def test_get_actor_props():
    """Actor props carry engine identity."""
    props = get_actor_props(actor_id=17)
    assert props["actor_id"] == 17
    assert props["is_anonymous"] is False


def test_get_actor_props_anonymous():
    """Anonymous actor flag."""
    props = get_actor_props(is_anonymous=True)
    assert props["is_anonymous"] is True
    assert props["actor_id"] is None


def test_get_org_props():
    """Org props carry organization fields."""
    props = get_org_props(org_id="org_x", org_name="Acme", org_plan="pro")
    assert props["org_id"] == "org_x"
    assert props["org_name"] == "Acme"
    assert props["org_plan"] == "pro"


def test_get_org_props_empty():
    """Org props return None fields when not provided."""
    props = get_org_props()
    assert props["org_id"] is None
    assert props["org_name"] is None


def test_get_session_props():
    """Session props include ID and start time."""
    props = get_session_props(
        session_id="sess_1", session_start_time="2026-03-12T15:30:00.000Z"
    )
    assert props["session_id"] == "sess_1"
    assert props["session_start_time"] == "2026-03-12T15:30:00.000Z"


def test_get_session_props_auto_id():
    """Session ID auto-generated when not provided."""
    props = get_session_props()
    uuid.UUID(props["session_id"])


def test_get_error_props_no_error():
    """Error props return empty dict when no error."""
    props = get_error_props()
    assert props == {}


def test_get_error_props_with_exception():
    """Error props capture exception details."""
    try:
        raise ValueError("something went wrong")
    except ValueError as e:
        props = get_error_props(
            error=e, error_code="VAL_001", error_category="validation"
        )

    assert props["error_code"] == "VAL_001"
    assert props["error_category"] == "validation"
    assert props["error_message"] == "something went wrong"
    assert props["is_retryable"] is False
    assert props["exception_type"] == "ValueError"
    assert "stacktrace" in props


def test_get_error_props_truncation():
    """Error message is truncated at 2KB."""
    long_msg = "x" * 5000
    try:
        raise RuntimeError(long_msg)
    except RuntimeError as e:
        props = get_error_props(error=e)

    assert len(props["error_message"]) == 2048


def test_build_event_canonical_fields():
    """build_event produces all canonical envelope fields."""
    # Clear env to get predictable defaults
    for var in ("APP_ENV", "SERVICE_NAME", "SERVICE_VERSION", "PROJECT"):
        os.environ.pop(var, None)

    event = build_event(
        name="TestEvent",
        kind="audit",
        event_type="test",
        outcome="completed",
        severity="INFO",
        context={"key": "value"},
    )

    # event_props
    assert event["event_name"] == "TestEvent"
    assert event["event_kind"] == "audit"
    assert event["event_type"] == "test"
    assert event["event_outcome"] == "completed"
    assert event["severity"] == "INFO"
    assert event["source_type"] == "backend"
    uuid.UUID(event["event_id"])  # Valid UUID
    assert event["event_time"].endswith("Z")

    # system_props (defaults)
    assert event["environment"] == "development"
    assert event["service"] == "api"
    assert event["project"] == "yoke"

    # context
    assert event["context"] == {"key": "value"}


def test_build_event_extra_props_merge():
    """Extra kwargs merge into envelope root."""
    actor = get_actor_props(actor_id=17)
    event = build_event(
        name="Test", kind="audit", event_type="test", **actor
    )
    assert event["actor_id"] == 17
    assert "user_id" not in event


def test_build_event_extra_props_override_system():
    """Explicit system props override auto-resolved ones."""
    system = get_system_props(service="worker", project="buzz")
    event = build_event(
        name="Test", kind="audit", event_type="test", **system
    )
    assert event["service"] == "worker"
    assert event["project"] == "buzz"


def test_build_event_context_field_truncation():
    """Context string fields exceeding 2KB are truncated."""
    long_value = "a" * 5000
    event = build_event(
        name="Test",
        kind="system",
        event_type="test",
        context={"big_field": long_value},
    )
    assert len(event["context"]["big_field"]) == 2048


def test_build_event_envelope_size_limit():
    """Envelopes exceeding 64KB have context replaced."""
    # Each field is <=2KB after truncation, but 40 fields x 2KB = 80KB > 64KB
    huge_context = {f"field_{i}": "x" * 2000 for i in range(40)}
    event = build_event(
        name="Test", kind="system", event_type="test", context=huge_context
    )
    assert event["context"] == {"_truncated": True}


def test_build_event_empty_context():
    """Missing context defaults to empty dict."""
    event = build_event(name="Test", kind="system", event_type="test")
    assert event["context"] == {}


def test_build_event_custom_event_id():
    """Pre-generated event_id is used when provided."""
    event = build_event(
        name="Test",
        kind="system",
        event_type="test",
        event_id="custom-uuid-here",
    )
    assert event["event_id"] == "custom-uuid-here"


def test_build_event_custom_event_time():
    """Pre-set event_time is used when provided."""
    event = build_event(
        name="Test",
        kind="system",
        event_type="test",
        event_time="2026-01-01T00:00:00.000Z",
    )
    assert event["event_time"] == "2026-01-01T00:00:00.000Z"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
