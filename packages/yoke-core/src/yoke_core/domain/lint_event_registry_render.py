"""Deny-payload render helpers for the lint-event-registry hook.

Split out of :mod:`yoke_core.domain.lint_event_registry` to keep the
authored hook entry-point module under the 350-line cap. These helpers
own the operator-visible deny payload formatting; the entry-point imports
them and uses them inside ``decide``.

The deny reason teaches the one registration path: a row in the code
event catalog, which every boot projects into ``event_registry``.
"""

from __future__ import annotations

import json

CHECK_ID = "unregistered_event"


def build_deny_reason(event_name: str) -> str:
    """Render the operator-visible deny reason string."""
    return (
        f"BLOCKED: emit-event.sh --name '{event_name}' is not registered in "
        "event_registry.\n"
        "Register it from a Yoke source checkout: add its row to "
        "packages/yoke-core/src/yoke_core/domain/event_catalog.py, run "
        "`python3 -m yoke_core.domain.event_catalog_render`, and ship the "
        "change; every boot registers the catalog."
    )


def build_deny_json(event_name: str) -> str:
    """Serialize a PreToolUse deny payload for *event_name*.

    The JSON is serialized with explicit separators that match the shell
    test suite's ``"permissionDecision": "deny"`` substring check.
    """
    reason = build_deny_reason(event_name)
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    return json.dumps(payload, separators=(", ", ": "))
