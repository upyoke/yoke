"""Bound side-effect-free registered handlers before transport abandonment.

The deadline is checked at native-call boundaries: each SQL statement carries
the remaining budget as its server-side timeout, nested HTTP reads inherit it,
and the budget is checked again when the handler returns. Python code between
those boundaries is never interrupted, so a subprocess or driver frame always
finishes or times out on its own terms.
"""

from __future__ import annotations

from yoke_contracts.api.function_call import FunctionError, HandlerOutcome
from yoke_contracts.read_deadline import (
    FUNCTION_RESPONSE_TIMEOUT_SECONDS,
    READ_RESPONSE_RESERVE_SECONDS,
    ReadDeadlineExceeded,
    read_budget,
)
from yoke_core.domain.function_connection_loss import (
    retry_dropped_connection,
    side_effect_free,
)
from yoke_core.domain.handler_execution_context import invoke_resolved_handler


def driver_call(method, *args, **kwargs):
    try:
        return method(*args, **kwargs)
    except Exception as exc:
        if getattr(exc, "sqlstate", None) == "57014":
            raise ReadDeadlineExceeded("read_deadline_exceeded") from exc
        raise


def invoke_handler(entry, request):
    if not side_effect_free(entry):
        return invoke_resolved_handler(entry.handler, request)
    seconds = FUNCTION_RESPONSE_TIMEOUT_SECONDS - READ_RESPONSE_RESERVE_SECONDS
    try:
        with read_budget(seconds):
            # A dropped connection retries inside the same budget, so the
            # second attempt cannot outlive the transport waiting on it.
            return retry_dropped_connection(
                lambda: invoke_resolved_handler(entry.handler, request)
            )
    except ReadDeadlineExceeded:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="read_deadline_exceeded",
                message=f"{entry.function_id} exceeded its {seconds:g}s server read deadline.",
            ),
        )
