"""Per-message hook settlement from the composed reply, not the lease."""

from __future__ import annotations

import re
from dataclasses import dataclass

from yoke_contracts.hook_context_compose import (
    POINTER_BEGIN,
    overflow_lease_marker,
    token_delivered,
)
from yoke_contracts.session_control.wake_delivery import (
    HOOK_INJECTED_RESULT,
    INLINE_OVERFLOW_RESULT,
)


_SHIPPED_RE = re.compile(r"--- BEGIN YOKE SESSION MESSAGE ([0-9a-fA-F-]{36}) ---")
_POINTER_READ_RE = re.compile(r"Read: yoke messages get ([0-9a-fA-F-]{36})")


@dataclass(frozen=True)
class LeaseSettlement:
    injected: bool
    result: str
    message_results: dict[str, str]


def classify_lease_settlement(
    rendered_text: str,
    *,
    denied: bool,
    lease_id: str,
    token: str,
) -> LeaseSettlement:
    """Map the composed reply onto per-message hook result codes.

    A receipt is injected only when its body envelope shipped. A pointer
    names a body that cannot fit even alone. Anything else this lease held
    stays pending for a later hook's own budget.
    """
    if denied:
        return LeaseSettlement(False, "dropped_by_sibling_denial", {})
    shipped = set(_SHIPPED_RE.findall(rendered_text))
    pointed = set(_POINTER_READ_RE.findall(rendered_text)) - shipped
    message_results = {message_id: HOOK_INJECTED_RESULT for message_id in shipped}
    message_results.update(
        {message_id: INLINE_OVERFLOW_RESULT for message_id in pointed}
    )
    if shipped and not pointed:
        return LeaseSettlement(True, HOOK_INJECTED_RESULT, message_results)
    if pointed and not shipped:
        return LeaseSettlement(False, INLINE_OVERFLOW_RESULT, message_results)
    if shipped and pointed:
        return LeaseSettlement(False, INLINE_OVERFLOW_RESULT, message_results)
    overflow = bool(
        POINTER_BEGIN in rendered_text
        and overflow_lease_marker(lease_id) in rendered_text
    )
    if overflow:
        return LeaseSettlement(False, INLINE_OVERFLOW_RESULT, {})
    if token_delivered(rendered_text, token):
        return LeaseSettlement(True, HOOK_INJECTED_RESULT, {})
    return LeaseSettlement(False, "render_output_missing", {})


__all__ = ["LeaseSettlement", "classify_lease_settlement"]
