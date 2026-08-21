"""Event-specific Stop hold/allow rendering for Claude, Codex, and Cursor.

PreToolUse permission envelopes are not reused. Allow stdout matches the
measured wire: Claude empty, Codex ``{}``, Cursor ``{}``. Hold uses each
harness's continuation channel so the same main agent resumes.
"""

from __future__ import annotations

import json

from yoke_core.hooks.decision_render import (
    _collect_additional_contexts,
    _collect_deny_narratives,
    _join_narratives,
    _render_additional_context_envelope,
)
from yoke_core.hooks.types import HookDecision


def _hold_reason(decisions: list[HookDecision]) -> str:
    return _join_narratives(_collect_deny_narratives(decisions))


def render_claude_stop(decisions: list[HookDecision]) -> tuple[str, int]:
    """Claude Stop: ``decision/block`` hold, empty allow, exit 0."""
    reason = _hold_reason(decisions)
    if reason:
        return json.dumps({"decision": "block", "reason": reason}), 0
    contexts = _collect_additional_contexts(decisions)
    if contexts:
        return (_render_additional_context_envelope(contexts, "Stop"), 0)
    return ("", 0)


def render_codex_stop(decisions: list[HookDecision]) -> tuple[str, int]:
    """Codex Stop: ``decision/block`` hold; allow stays empty so dispatch owns ``{}``."""
    reason = _hold_reason(decisions)
    if reason:
        return json.dumps({"decision": "block", "reason": reason}), 0
    return ("", 0)


def render_cursor_stop(decisions: list[HookDecision]) -> tuple[str, int]:
    """Cursor Stop: ``followup_message`` hold; allow is ``{}``."""
    reason = _hold_reason(decisions)
    if reason:
        return json.dumps({"followup_message": reason}), 0
    return ("{}", 0)


__all__ = [
    "render_claude_stop",
    "render_codex_stop",
    "render_cursor_stop",
]
