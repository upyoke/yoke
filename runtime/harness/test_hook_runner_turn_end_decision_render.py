"""Stop hold/allow wire contracts for Claude, Codex, and Cursor."""

from __future__ import annotations

import json

from yoke_core.domain.turn_end_promised_work_gate import DIRECTIVE
from yoke_core.hooks.decision_render import (
    render_claude_decision,
    render_codex_decision,
    render_cursor_decision,
)
from yoke_core.hooks.types import HookDecision, Outcome


def _hold() -> HookDecision:
    return HookDecision(
        outcome=Outcome.DENY, message=DIRECTIVE, block=True,
    )


def _allow() -> HookDecision:
    return HookDecision(outcome=Outcome.ALLOW)


def test_claude_stop_allow_stays_empty() -> None:
    assert render_claude_decision([], "Stop") == ("", 0)
    assert render_claude_decision([_allow()], "Stop") == ("", 0)


def test_claude_stop_hold_uses_decision_block() -> None:
    stdout, code = render_claude_decision([_hold()], "Stop")
    assert code == 0
    assert json.loads(stdout) == {"decision": "block", "reason": DIRECTIVE}


def test_claude_pretool_deny_is_unchanged() -> None:
    stdout, code = render_claude_decision([_hold()], "PreToolUse")
    assert code == 2
    assert stdout == DIRECTIVE


def test_codex_stop_allow_stays_empty_for_dispatch_owned_object() -> None:
    assert render_codex_decision([], "Stop") == ("", 0)
    assert render_codex_decision([_allow()], "Stop") == ("", 0)


def test_codex_stop_hold_uses_decision_block_not_permission_envelope() -> None:
    stdout, code = render_codex_decision([_hold()], "Stop")
    assert code == 0
    payload = json.loads(stdout)
    assert payload == {"decision": "block", "reason": DIRECTIVE}
    assert "hookSpecificOutput" not in payload


def test_codex_pretool_deny_is_unchanged() -> None:
    stdout, code = render_codex_decision([_hold()], "PreToolUse")
    assert code == 0
    hook = json.loads(stdout)["hookSpecificOutput"]
    assert hook["permissionDecision"] == "deny"


def test_cursor_stop_allow_stays_empty_object() -> None:
    assert render_cursor_decision([], "Stop") == ("{}", 0)
    assert render_cursor_decision([_allow()], "Stop") == ("{}", 0)


def test_cursor_stop_hold_uses_followup_message() -> None:
    stdout, code = render_cursor_decision([_hold()], "Stop")
    assert code == 0
    assert json.loads(stdout) == {"followup_message": DIRECTIVE}


def test_cursor_session_end_allow_is_unchanged() -> None:
    assert render_cursor_decision([], "SessionEnd") == ("{}", 0)
    stdout, code = render_cursor_decision([_hold()], "SessionEnd")
    assert code == 0
    assert json.loads(stdout)["permission"] == "deny"
