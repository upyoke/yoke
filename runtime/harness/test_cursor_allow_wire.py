"""Cursor permission gates require a JSON verdict even without server policy."""

from __future__ import annotations

import json

import pytest

from yoke_contracts.hook_runner.cursor_response import cursor_allow_stdout
from yoke_contracts.hook_runner.project_scope import HookProjectScope
from yoke_harness.hooks import local_subset, relay_degrade
from yoke_harness.hooks.deadline import start_hook_deadline
from yoke_harness.hooks.decision_render import merge_allow_stdout, render_context_stdout
from yoke_harness.hooks.local_policy_common import DENY, PolicyResult


@pytest.mark.parametrize("event", ["PreToolUse", "apply_patch"])
@pytest.mark.parametrize("project_id", [None, 7])
@pytest.mark.parametrize("deferred", [False, True])
def test_local_help_allow_is_a_native_permission_reply(
    event,
    project_id,
    deferred,
    tmp_path,
):
    # Reproduce the native beforeShellExecution payload from the host replay.
    result = local_subset.evaluate_local_subset(
        event,
        json.dumps(
            {
                "hook_event_name": "beforeShellExecution",
                "command": "yoke project refresh --help",
                "cwd": str(tmp_path),
                "workspace_roots": [str(tmp_path)],
            }
        ),
        "cursor",
        None,
        start_hook_deadline(),
        project_scope=HookProjectScope(project_id=project_id),
        collect_facts=deferred,
        lint_config_snapshot={},
    )
    assert result.exit_code == 0
    assert not result.denied
    assert json.loads(result.stdout) == {"permission": "allow"}


def test_local_deny_keeps_reason_and_native_verdict(monkeypatch, tmp_path):
    module = "yoke_core.domain.lint_main_commit"
    monkeypatch.setattr(local_subset, "_local_modules", lambda *a, **k: [module])
    monkeypatch.setitem(
        local_subset._POLICY_EVALUATORS,
        module,
        lambda payload: PolicyResult(DENY, "required refusal"),
    )
    result = local_subset.evaluate_local_subset(
        "PreToolUse",
        json.dumps({"cwd": str(tmp_path)}),
        "cursor",
        None,
        start_hook_deadline(),
        project_scope=HookProjectScope(project_id=7),
        lint_config_snapshot={},
    )
    assert result.denied
    payload = json.loads(result.stdout)
    assert payload["permission"] == "deny"
    assert "required refusal" in payload["agent_message"]


@pytest.mark.parametrize("event", ["PreToolUse", "apply_patch"])
def test_transport_fallback_supplies_permission_reply(event, monkeypatch, capsys):
    monkeypatch.setenv("YOKE_EXECUTOR", "cursor")
    monkeypatch.setattr(relay_degrade, "print_execution_provenance", lambda **k: None)
    assert relay_degrade.degrade_to_noop(event, "connection unavailable") == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"permission": "allow"}
    assert "YOKE_HOOK_DEGRADED" in captured.err


@pytest.mark.parametrize(
    "server",
    [
        {"permission": "allow"},
        {"permission": "deny", "agent_message": "server refusal"},
    ],
)
@pytest.mark.parametrize("reverse", [False, True])
def test_local_and_server_verdicts_remain_one_json_value(server, reverse):
    local = cursor_allow_stdout("PreToolUse")
    remote = json.dumps(server)
    first, second = (remote, local) if reverse else (local, remote)
    merged = merge_allow_stdout(first, second, "PreToolUse", cursor=True)
    assert json.loads(merged) == server


@pytest.mark.parametrize("event", ["SessionStart", "PostToolUse"])
def test_local_advisory_uses_native_context_on_supported_events(event):
    shared = json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": "required guidance",
            }
        }
    )
    assert json.loads(cursor_allow_stdout(event, shared)) == {
        "additional_context": "required guidance",
    }


def test_permission_advisory_does_not_replace_verdict():
    shared = json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": "advisory",
            }
        }
    )
    assert json.loads(cursor_allow_stdout("PreToolUse", shared)) == {
        "permission": "allow",
    }


def test_extra_context_on_permission_gate_keeps_valid_allow_reply():
    merged = merge_allow_stdout(
        cursor_allow_stdout("PreToolUse"),
        render_context_stdout("caller advisory", "PreToolUse", cursor=True),
        "PreToolUse",
        cursor=True,
    )
    assert json.loads(merged) == {"permission": "allow"}


@pytest.mark.parametrize("event", ["Stop", "SessionEnd"])
def test_lifecycle_allows_still_render_object(event):
    assert cursor_allow_stdout(event) == "{}"


def test_existing_denial_payload_is_preserved():
    deny = '{"permission":"deny","agent_message":"required refusal"}'
    assert cursor_allow_stdout("PreToolUse", deny) == deny
