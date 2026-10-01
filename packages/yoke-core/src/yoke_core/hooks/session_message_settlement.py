"""Per-message hook settlement from the composed reply, not the lease."""

from __future__ import annotations

import re
from dataclasses import dataclass

from yoke_contracts.hook_context_compose import (
    token_delivered,
)
from yoke_contracts.session_control.wake_delivery import (
    HOOK_INJECTED_RESULT,
)


_SHIPPED_RE = re.compile(r"--- BEGIN YOKE SESSION MESSAGE ([0-9a-fA-F-]{36}) ---")


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

    A full body or a stub counts as injected. Anything this lease held
    that did not fit stays pending for a later hook's own budget.
    """
    if denied:
        return LeaseSettlement(False, "dropped_by_sibling_denial", {})
    shipped = set(_SHIPPED_RE.findall(rendered_text))
    message_results = {message_id: HOOK_INJECTED_RESULT for message_id in shipped}
    if shipped:
        return LeaseSettlement(True, HOOK_INJECTED_RESULT, message_results)
    if token_delivered(rendered_text, token):
        return LeaseSettlement(True, HOOK_INJECTED_RESULT, {})
    return LeaseSettlement(False, "render_output_missing", {})


__all__ = ["LeaseSettlement", "classify_lease_settlement"]
