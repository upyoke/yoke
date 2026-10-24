"""Guards supply reasons; the shared renderer owns every harness envelope."""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

import pytest

from yoke_contracts.field_note_text import DENIAL_FOOTER
from yoke_contracts.hook_runner.denial_identity import attach_check_id
from yoke_contracts.hook_runner.hook_guard_catalog import GUARD_CATALOG
from yoke_core.domain import lint_git_stash_arg_order as guard
from yoke_core.hooks.decision_render import (
    render_claude_decision,
    render_codex_decision,
    render_cursor_decision,
)
from yoke_core.hooks.guard_denial_identity import bind
from yoke_core.hooks.types import HookContext, Outcome


@pytest.mark.parametrize("spec", GUARD_CATALOG, ids=lambda spec: spec.guard)
def test_guard_sources_and_helpers_cannot_construct_harness_envelopes(spec):
    """Check registered guards and their domain helpers, including embedded rules."""
    pending = [".".join(spec.module.split(".")[:3])]
    seen = set()
    while pending:
        module = pending.pop()
        if module in seen:
            continue
        seen.add(module)
        found = importlib.util.find_spec(module)
        assert found and found.origin, module
        source = Path(found.origin).read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                keys = [key.value for key in node.keys if isinstance(key, ast.Constant)]
                assert "hookSpecificOutput" not in keys, module
                assert "permissionDecision" not in keys, module
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                # The DB guard's rule fragments are executable source strings.
                assert '"permissionDecisionReason":' not in node.value, module
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith(
                    ("yoke_core.domain.lint_", "yoke_core.domain.path_claim_")
                ):
                    pending.append(node.module)


@pytest.mark.parametrize("harness", ["claude", "codex", "cursor"])
def test_converted_guard_renders_reason_footer_and_check_id(harness, monkeypatch):
    monkeypatch.setattr(guard, "_read_mode", lambda payload: "deny")
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "git stash push -- file -m reason"},
    }
    context = HookContext("PreToolUse", harness, harness, payload)
    decision = guard.evaluate(context)
    assert decision.outcome is Outcome.DENY
    assert decision.message == decision.audit_fields["reason"]
    assert not decision.message.startswith("{")
    bound = bind(decision, guard.__name__)
    expected = attach_check_id(f"{decision.message}\n\n{DENIAL_FOOTER}", guard.CHECK_ID)
    assert bound.message == expected
    assert bound.audit_fields["denial_reason"] == expected
    assert bound.audit_fields["check_id"] == guard.CHECK_ID
    renderers = {
        "claude": render_claude_decision,
        "codex": render_codex_decision,
        "cursor": render_cursor_decision,
    }
    text, code = renderers[harness]([bound], "PreToolUse")
    if harness == "claude":
        assert (text, code) == (expected, 2)
    elif harness == "codex":
        assert code == 0
        assert json.loads(text) == {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": expected,
            }
        }
    else:
        assert code == 0
        assert json.loads(text) == {
            "permission": "deny",
            "user_message": expected,
            "agent_message": expected,
        }
