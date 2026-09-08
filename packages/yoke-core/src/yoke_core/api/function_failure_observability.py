"""Bounded diagnostics for unexpected function-dispatch failures."""

from __future__ import annotations

import logging
from typing import Any, Mapping

from fastapi import Request

from yoke_core.api.observability import (
    REQUEST_ID_STATE_ATTR,
    environment_name,
    service_name,
    trace_context,
)


_LOGGER = logging.getLogger("yoke.api.functions")
_DIAGNOSTIC_VALUE_LIMIT = 160


def _diagnostic_value(value: Any) -> str:
    """Bound an identifier and keep control characters out of log fields."""
    return (
        str(value or "").replace("\r", " ").replace("\n", " ")[:_DIAGNOSTIC_VALUE_LIMIT]
    )


def record_function_failure(
    request: Request,
    envelope: Mapping[str, Any],
    exc: Exception,
) -> None:
    """Emit one bounded diagnostic without payloads or exception details."""
    try:
        function_id = _diagnostic_value(envelope.get("function"))
        function_request_id = _diagnostic_value(envelope.get("request_id"))
        http_request_id = _diagnostic_value(
            getattr(request.state, REQUEST_ID_STATE_ATTR, "")
        )
        context = {
            "function": function_id,
            "error_class": _diagnostic_value(type(exc).__name__),
        }
        if http_request_id:
            context["http_request_id"] = http_request_id
        extra = {
            "event_name": "FunctionCallHandlerFailed",
            "event_kind": "system",
            "event_type": "function_call",
            "service": service_name(),
            "environment": environment_name(),
            "request_id": function_request_id or http_request_id,
            "context": context,
        }
        extra.update(trace_context())
        _LOGGER.error("function_call_handler_failed", extra=extra)
    except Exception:
        return


__all__ = ["record_function_failure"]
