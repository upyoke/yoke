"""Result shaping for debug captures of one-time credentials."""

from __future__ import annotations

from typing import Any

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.domain.yoke_function_registry import RegistryEntry


ONE_TIME_SECRET_GUARDRAIL = "one_time_secret_result"


def debug_capture_result(
    entry: RegistryEntry,
    response: FunctionCallResponse,
) -> dict[str, Any]:
    """Describe guarded results without retaining their one-time values."""
    if ONE_TIME_SECRET_GUARDRAIL in entry.guardrails:
        return {
            "result_redacted": ONE_TIME_SECRET_GUARDRAIL,
            "result_keys": sorted(response.result),
        }
    return {"result": dict(response.result)}
