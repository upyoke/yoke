"""Redact dispatcher responses before returning them to the caller."""

from __future__ import annotations

from typing import Sequence

from yoke_cli.transport.public_ref_display import redact_response
from yoke_contracts.api.function_call import FunctionCallResponse


def settle_response(
    response: FunctionCallResponse, sensitive_values: Sequence[str] = ()
) -> FunctionCallResponse:
    return redact_response(response, tuple(sensitive_values))


__all__ = ["settle_response"]
