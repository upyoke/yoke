"""Shared payload-shape validation for browser function-call envelopes."""

from __future__ import annotations

from typing import Any

from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError


def browser_payload_refusal(envelope: dict[str, Any]) -> FunctionCallResponse | None:
    """Refuse JSON values that payload binding must never coerce into objects."""
    if isinstance(envelope.get("payload", {}), dict):
        return None
    request_id = envelope.get("request_id")
    return FunctionCallResponse(
        success=False,
        function=str(envelope.get("function") or ""),
        version=str(envelope.get("version") or "v1"),
        request_id=str(request_id) if request_id is not None else None,
        error=FunctionError(
            code="envelope_invalid",
            message="payload must be a JSON object; send payload: {} for an empty payload",
        ),
    )
