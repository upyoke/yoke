"""Smoke tests for the Cursor adapter capability and decision renderer.

Full universal-ordering parity tests live in
`runtime/harness/test_hook_runner_parity.py`. This file covers the
adapter's own contract (import works, family is correct, declared
omissions match the harness's injection channels, the adapter file stays
data-only) plus the Cursor decision renderer's wire shapes.
"""

from __future__ import annotations

import json
from pathlib import Path

from yoke_core.hooks import cursor_adapter
from yoke_core.hooks.cursor_payload import parse_payload
from yoke_core.hooks.adapter_capability import AdapterCapability
from yoke_core.hooks.capability_resolve import resolve_capability
from yoke_core.hooks.decision_render import render_cursor_decision
from yoke_core.hooks.types import HookDecision, Outcome


def test_capability_imports() -> None:
    from yoke_core.hooks.cursor_adapter import CAPABILITY

    assert isinstance(CAPABILITY, AdapterCapability)


def test_capability_family_is_cursor() -> None:
    from yoke_core.hooks.cursor_adapter import CAPABILITY

    assert CAPABILITY.family == "cursor"


def test_no_chain_omissions_declared() -> None:
    # Cursor runs the same universal chains as Claude and Codex; the
    # preToolUse no-allow-time-injection constraint is owned by the
    # decision renderer, not by chain omissions.
    from yoke_core.hooks.cursor_adapter import CAPABILITY

    assert CAPABILITY.apply_patch_chain_omissions == frozenset()
    assert CAPABILITY.pretool_omissions == frozenset()


def test_subprocess_modules_carveout() -> None:
    from yoke_core.hooks.cursor_adapter import CAPABILITY

    assert CAPABILITY.subprocess_modules == frozenset()


def test_callables_bound_by_reference_not_wrappers() -> None:
    from yoke_core.hooks.cursor_adapter import CAPABILITY

    assert CAPABILITY.payload_parser is parse_payload
    assert CAPABILITY.decision_renderer is render_cursor_decision


def test_resolve_capability_three_way_family() -> None:
    assert resolve_capability("cursor").family == "cursor"
    assert resolve_capability("cursor-cli").family == "cursor"
    assert resolve_capability("cursor-desktop").family == "cursor"
    assert resolve_capability("codex-desktop").family == "codex"
    assert resolve_capability("claude-code").family == "claude"


def test_deny_renders_permission_envelope_with_agent_message() -> None:
    deny = HookDecision(outcome=Outcome.DENY, message="blocked: reason")
    stdout, exit_code = render_cursor_decision([deny], "PreToolUse")
    assert exit_code == 0
    envelope = json.loads(stdout)
    assert envelope["permission"] == "deny"
    assert envelope["agent_message"] == "blocked: reason"
    assert envelope["user_message"] == "blocked: reason"


def test_deny_unwraps_pre_rendered_hook_specific_output_envelope() -> None:
    # Policy modules may set decision.message to the already-rendered
    # hookSpecificOutput deny envelope (the Claude/Codex wire shape); the
    # cursor renderer must carry the plain narrative in both message
    # fields, never a stringified JSON blob.
    reason = "BLOCKED: use the yoke CLI instead."
    pre_rendered = json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    )
    deny = HookDecision(outcome=Outcome.DENY, message=pre_rendered)
    stdout, exit_code = render_cursor_decision([deny], "PreToolUse")
    assert exit_code == 0
    envelope = json.loads(stdout)
    assert envelope["permission"] == "deny"
    assert envelope["agent_message"] == reason
    assert envelope["user_message"] == reason


def test_allow_is_explicit_on_permission_events_only() -> None:
    stdout, exit_code = render_cursor_decision([], "PreToolUse")
    assert (json.loads(stdout), exit_code) == ({"permission": "allow"}, 0)
    stdout, exit_code = render_cursor_decision([], "SessionEnd")
    assert (stdout, exit_code) == ("{}", 0)
    stdout, exit_code = render_cursor_decision([], "Stop")
    assert (stdout, exit_code) == ("{}", 0)


def test_context_injection_only_on_accepting_events() -> None:
    advisory = HookDecision(
        outcome=Outcome.ALLOW,
        message="",
        audit_fields={"additionalContext": "orientation body"},
    )
    stdout, _ = render_cursor_decision([advisory], "SessionStart")
    assert json.loads(stdout) == {"additional_context": "orientation body"}
    stdout, _ = render_cursor_decision([advisory], "PostToolUse")
    assert json.loads(stdout) == {"additional_context": "orientation body"}
    # preToolUse has no allow-time injection channel: advisory drops.
    stdout, _ = render_cursor_decision([advisory], "PreToolUse")
    assert json.loads(stdout) == {"permission": "allow"}


def test_deny_wins_over_advisory() -> None:
    deny = HookDecision(outcome=Outcome.DENY, message="no")
    advisory = HookDecision(
        outcome=Outcome.ALLOW,
        message="",
        audit_fields={"additionalContext": "hint"},
    )
    stdout, _ = render_cursor_decision([advisory, deny], "PostToolUse")
    envelope = json.loads(stdout)
    assert envelope["permission"] == "deny"
    assert "hint" not in stdout


def test_adapter_module_has_zero_def_declarations() -> None:
    adapter_path = Path(cursor_adapter.__file__).resolve()
    source = adapter_path.read_text(encoding="utf-8")
    def_lines = [line for line in source.splitlines() if line.startswith("def ")]
    assert def_lines == [], (
        f"adapter.py must contain zero def declarations, found: {def_lines}"
    )


def test_adapter_module_under_140_lines() -> None:
    adapter_path = Path(cursor_adapter.__file__).resolve()
    line_count = len(adapter_path.read_text(encoding="utf-8").splitlines())
    assert line_count <= 140, f"adapter.py is {line_count} lines, must be <=140"
