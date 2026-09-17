"""Bounded failure projections for dispatcher telemetry.

Dispatcher events fire once per call, so any free-form text they copy is
paid for on every call forever. Two values are free-form: a failed call's
``FunctionError.message`` and a degraded step's ``FunctionWarning.detail``.
This module clips both to :data:`FAILURE_TEXT_MAX_CHARS` and marks the
clip, so a reader can recognize and act on the failure without the event
carrying a document. The untruncated text always remains on the response
envelope the caller already received.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from yoke_contracts.api.function_call import FunctionError, FunctionWarning


# Enough to identify which failure this was — a refusal headline, a
# constraint name, the first frame of a diagnostic — without carrying a
# whole document per call.
FAILURE_TEXT_MAX_CHARS = 400


def clip(text: str) -> Tuple[str, bool]:
    """Return ``(text_at_or_under_the_cap, was_clipped)``."""
    if len(text) <= FAILURE_TEXT_MAX_CHARS:
        return text, False
    return text[:FAILURE_TEXT_MAX_CHARS], True


def error_event_context(error: Optional[FunctionError]) -> Dict[str, Any]:
    """Project a failed call's error to bounded, actionable context keys.

    A reader diagnosing a failure needs the code it dispatches on and
    enough message to recognize which failure this was — not a document.
    ``error_message_clipped`` marks a truncated message so a clipped one
    is never read as the whole text. ``recovery_hint`` is deliberately
    omitted: it carries the constant field-note footer, so it would be
    per-call bytes that say nothing about this particular call.
    """
    if error is None:
        return {}
    message, clipped = clip(error.message or "")
    context: Dict[str, Any] = {
        "error_code": error.code,
        "error_message": message,
    }
    if clipped:
        context["error_message_clipped"] = True
    if error.jsonpath:
        context["error_jsonpath"] = error.jsonpath
    return context


def clipped_warning(warning: FunctionWarning) -> Dict[str, Any]:
    """Return one warning's fields with its free-form detail clipped."""
    fields = warning.model_dump()
    detail, was_clipped = clip(str(fields.get("detail") or ""))
    fields["detail"] = detail
    if was_clipped:
        fields["detail_clipped"] = True
    return fields


__all__ = [
    "FAILURE_TEXT_MAX_CHARS",
    "clip",
    "clipped_warning",
    "error_event_context",
]
