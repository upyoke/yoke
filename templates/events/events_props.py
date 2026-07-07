"""
GENERATED FROM templates/events/events_props.py -- do not edit copied output.

Sibling of templates/events/events.py. See templates/events/README.md.

Property group builders for the structured event envelope. Each builder
resolves a property group from explicit arguments, with environment-variable
fallbacks for system props.

Copy this file alongside events.py into your project. The post-split
events.py re-exports these names so existing `from events import get_*_props`
callers continue to work without modification.
"""
import os
import traceback
import uuid
from typing import Optional


# ---------------------------------------------------------------------------
# Property Group Builders
# ---------------------------------------------------------------------------

def get_system_props(
    service: Optional[str] = None,
    project: Optional[str] = None,
    environment: Optional[str] = None,
    service_version: Optional[str] = None,
) -> dict:
    """
    Resolve system properties.

    Explicit arguments take precedence over environment variables.
    """
    return {
        "environment": environment or os.environ.get("APP_ENV", "development"),
        "service": service or os.environ.get("SERVICE_NAME", "api"),
        "service_version": service_version or os.environ.get("SERVICE_VERSION"),
        "project": project or os.environ.get("PROJECT", "yoke"),
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
    """Build user identity properties."""
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


def get_session_props(
    session_id: Optional[str] = None,
    session_start_time: Optional[str] = None,
) -> dict:
    """Build session properties."""
    return {
        "session_id": session_id or str(uuid.uuid4()),
        "session_start_time": session_start_time,
    }


def get_error_props(
    error: Optional[Exception] = None,
    error_code: Optional[str] = None,
    error_category: str = "unknown",
    is_retryable: bool = False,
) -> dict:
    """
    Build error properties from an exception or explicit values.

    Returns empty dict when no error is provided (conditional group).

    Reads ``MAX_CONTEXT_FIELD_BYTES`` and ``MAX_STACKTRACE_BYTES`` from the
    sibling ``events`` module so the size limits remain defined in a single
    place. The lazy import avoids a module-level circular dependency between
    events.py and events_props.py.
    """
    if error is None:
        return {}
    from events import MAX_CONTEXT_FIELD_BYTES, MAX_STACKTRACE_BYTES
    return {
        "error_code": error_code,
        "error_category": error_category,
        "error_message": str(error)[:MAX_CONTEXT_FIELD_BYTES],
        "is_retryable": is_retryable,
        "exception_type": type(error).__name__,
        "stacktrace": traceback.format_exc()[-MAX_STACKTRACE_BYTES:],
    }
