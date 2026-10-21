"""Only a guard that ran and denied blocks; the switch turns Yoke hooks off."""

from __future__ import annotations

import json

import pytest

from yoke_contracts.hook_runner import safety
from yoke_contracts.hook_runner.degraded import (
    HOOKS_OFF_ENV,
    degraded_allow_stdout,
    infrastructure_reply,
    plain_allow_stdout,
)
from runtime.harness.hook_degraded_test_support import assert_degraded_allow

EXECUTORS = ["claude-code", "codex", "cursor"]
EVENTS = ["PreToolUse", "UserPromptSubmit", "PostToolUse", "SessionStart", "Stop"]


@pytest.fixture(autouse=True)
def isolated_safety(tmp_path, monkeypatch):
    monkeypatch.setattr(safety, "_state_path", lambda: tmp_path / "counters.json")
    monkeypatch.delenv(HOOKS_OFF_ENV, raising=False)


@pytest.fixture
def hooks(monkeypatch):
    from yoke_cli.commands.adapters import hooks

    monkeypatch.setattr(hooks, "_read_stdin", lambda: '{"session_id":"degraded"}')
    return hooks


@pytest.mark.parametrize("executor", EXECUTORS)
@pytest.mark.parametrize("event", EVENTS)
def test_switch_allows_without_evaluating(executor, event, hooks, monkeypatch, capsys):
    monkeypatch.setenv("YOKE_EXECUTOR", executor)
    monkeypatch.setenv(HOOKS_OFF_ENV, "1")
    monkeypatch.setattr(
        hooks, "_dispatch_hook", lambda *_a: pytest.fail("switch must skip hooks")
    )
    assert hooks.hook_evaluate([event]) == 0
    captured = capsys.readouterr()
    assert captured.out == plain_allow_stdout(event, executor)
    assert HOOKS_OFF_ENV in captured.err


@pytest.mark.parametrize("value", ["", "0", "no"])
def test_switch_stays_on_unless_set(value, hooks, monkeypatch):
    monkeypatch.setenv(HOOKS_OFF_ENV, value)
    monkeypatch.setattr(hooks, "_dispatch_hook", lambda *_a: 7)
    assert hooks.hook_evaluate(["PreToolUse"]) == 7


@pytest.mark.parametrize(
    "executor,deny,code",
    [
        ("claude-code", "guard refused", 2),
        (
            "codex",
            json.dumps(
                {"hookSpecificOutput": {"permissionDecision": "deny"}}
            ),
            0,
        ),
        ("cursor", json.dumps({"permission": "deny", "agent_message": "no"}), 0),
    ],
)
def test_a_guard_that_ran_and_denied_still_blocks(
    executor, deny, code, hooks, monkeypatch, capsys
):
    monkeypatch.setenv("YOKE_EXECUTOR", executor)

    def denied(*_a):
        print(deny, end="")
        return code

    monkeypatch.setattr(hooks, "_dispatch_hook", denied)
    assert hooks.hook_evaluate(["PreToolUse"]) == code
    captured = capsys.readouterr()
    assert captured.out == deny
    assert "NOT being enforced" not in captured.err


@pytest.mark.parametrize("executor", EXECUTORS)
@pytest.mark.parametrize("event", EVENTS)
def test_resident_failure_allows_every_event_on_every_harness(
    executor, event, hooks, monkeypatch, capsys
):
    monkeypatch.setenv("YOKE_EXECUTOR", executor)

    def unavailable(*_a):
        raise OSError("resident socket refused")

    monkeypatch.setattr(hooks, "_dispatch_hook", unavailable)
    assert hooks.hook_evaluate([event]) == 0
    captured = capsys.readouterr()
    assert_degraded_allow(executor, event, captured.out, "OSError")
    assert "NOT being enforced" in captured.err


def test_every_degraded_call_repeats_the_full_warning(capsys):
    first = infrastructure_reply("PreToolUse", "claude-code", "relay unreachable")
    second = infrastructure_reply("PreToolUse", "claude-code", "relay unreachable")
    assert first == second
    assert_degraded_allow("claude-code", "PreToolUse", second, "relay unreachable")
    assert capsys.readouterr().err.count("NOT being enforced") == 2


def test_degraded_allow_keeps_computed_context():
    preserved = json.dumps(
        {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "x"}}
    )
    body = json.loads(degraded_allow_stdout("PostToolUse", "codex", "warn", preserved))
    assert body["hookSpecificOutput"]["additionalContext"] == "x"
    assert body["systemMessage"] == "warn"
