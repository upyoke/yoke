"""Broken hook infrastructure must never purchase another model turn."""

from __future__ import annotations

import json

import pytest

from yoke_contracts.hook_runner import safety
from yoke_contracts.hook_runner.project_scope import HookProjectScope


@pytest.fixture(autouse=True)
def isolated_safety(tmp_path, monkeypatch):
    monkeypatch.setattr(safety, "_state_path", lambda: tmp_path / "counters.json")
    monkeypatch.delenv("YOKE_SESSION_ID", raising=False)


@pytest.mark.parametrize("executor", ["claude-code", "codex", "cursor"])
@pytest.mark.parametrize("event", ["Stop", "SessionStart", "SessionEnd"])
def test_broken_scope_local_subset_allows_lifecycle(executor, event, capsys):
    from yoke_harness.hooks.deadline import start_hook_deadline
    from yoke_harness.hooks.local_subset import evaluate_local_subset

    result = evaluate_local_subset(
        event,
        '{"session_id":"broken-config"}',
        executor,
        None,
        start_hook_deadline(),
        project_scope=HookProjectScope(failure="project_key_invalid"),
    )
    assert result.exit_code == 0
    assert not result.denied
    assert result.stdout in ("", "{}")
    assert "hook_scope_unavailable" in capsys.readouterr().err


@pytest.mark.parametrize("executor", ["claude-code", "codex", "cursor"])
@pytest.mark.parametrize("event", ["Stop", "SessionStart", "SessionEnd"])
def test_broken_scope_shared_runner_allows_lifecycle(
    executor, event, monkeypatch, capsys
):
    from yoke_core.hooks import runner
    from yoke_core.hooks.capability_resolve import resolve_capability
    from yoke_core.hooks.remote_policy import RunControls

    monkeypatch.setattr(runner, "build_context", lambda **kwargs: None)
    controls = RunControls(
        project_scope=HookProjectScope(failure="project_key_invalid")
    )
    text, code = runner.run_event(
        event,
        capability=resolve_capability(executor),
        stdin_data='{"session_id":"broken-config"}',
        controls=controls,
    )
    assert (text, code) == (
        safety.allow_stdout(executor) if event != "SessionStart" else "",
        0,
    )
    assert controls.final_outcome == "allow"
    assert controls.denial_audit == {}
    assert "repair" in capsys.readouterr().err


@pytest.mark.parametrize("executor", ["claude-code", "codex", "cursor"])
@pytest.mark.parametrize(
    "event", ["Stop", "SessionStart", "SessionEnd", "PreToolUse", "UserPromptSubmit"]
)
def test_cli_config_crash_is_lifecycle_allow_and_tool_refusal(
    executor, event, monkeypatch, capsys
):
    from yoke_cli.commands.adapters import hooks

    monkeypatch.setenv("YOKE_EXECUTOR", executor)
    monkeypatch.setattr(hooks, "_read_stdin", lambda: '{"session_id":"config-crash"}')

    def broken(*args, **kwargs):
        print('{"decision":"block","reason":"partial"}')
        raise RuntimeError("project_key_invalid")

    monkeypatch.setattr(hooks, "_dispatch_hook", broken)
    code = hooks.hook_evaluate([event])
    captured = capsys.readouterr()
    assert "partial" not in captured.out
    if event in safety.LIFECYCLE_EVENTS:
        assert code == 0
        assert captured.out in ("", "{}")
        assert "hook_infrastructure_unavailable" in captured.err
    else:
        assert code == (0 if executor in {"codex", "cursor"} else 2)
        assert "hook_infrastructure_unavailable" in captured.out


@pytest.mark.parametrize(
    "executor,body",
    [
        ("claude-code", {"decision": "block", "reason": "pending work"}),
        ("codex", {"decision": "block", "reason": "pending work"}),
        ("cursor", {"followup_message": "pending work"}),
    ],
)
def test_repeated_policy_stop_blocks_are_bounded_across_invocations(executor, body):
    payload = {"session_id": "same-session"}
    text = json.dumps(body)
    for _ in range(safety.BLOCK_LIMIT):
        assert safety.protect_stop("Stop", payload, text, 0, executor) == (text, 0)
    for _ in range(5):
        assert safety.protect_stop("Stop", payload, text, 0, executor) == (
            safety.allow_stdout(executor),
            0,
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"stop_hook_active": True},
        {"stop_hook_active": "true"},
        {"stop_hook_active": "1"},
        {"loop_count": 1},
    ],
)
def test_native_stop_reentry_cannot_continue(payload):
    assert safety.protect_stop("Stop", payload, '{"decision":"block"}', 0, "codex") == (
        "{}",
        0,
    )


def test_brake_state_failure_allows_stop_but_never_tools(monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(safety, "_update", broken)
    assert safety.protect_stop("Stop", {}, "blocked", 2, "claude") == ("", 0)
    assert safety.protect_stop("PreToolUse", {}, "blocked", 2, "claude") == (
        "blocked",
        2,
    )


def test_infrastructure_messages_shorten_without_changing_denial():
    payload = {"session_id": "rate-limit"}
    first = safety.infrastructure_reply(
        "PreToolUse", payload, "codex", "hook_scope_unavailable: project_key_invalid"
    )
    second = safety.infrastructure_reply(
        "PreToolUse", payload, "codex", "hook_scope_unavailable: project_key_invalid"
    )
    assert first[1:] == second[1:] == (0, True)
    assert "project_key_invalid" in first[0]
    assert "repeated failure" in second[0]
    assert "project_key_invalid" not in second[0]


@pytest.mark.parametrize("executor", ["claude-code", "codex", "cursor"])
def test_actual_malformed_machine_config_cannot_hold_cli_stop(
    executor, tmp_path, monkeypatch, capsys
):
    from yoke_cli.commands.adapters import hooks
    from yoke_contracts.machine_config import runtime

    config = tmp_path / "config.json"
    config.write_text("{broken")
    monkeypatch.setenv("YOKE_EXECUTOR", executor)
    monkeypatch.setattr(hooks, "_read_stdin", lambda: '{"session_id":"malformed"}')
    monkeypatch.setattr(
        hooks, "_dispatch_hook", lambda *_a: runtime.load_config(config)
    )
    assert hooks.hook_evaluate(["Stop"]) == 0
    assert capsys.readouterr().out == safety.allow_stdout(executor)


def test_rate_limit_expires_and_stop_reasons_are_independent(monkeypatch):
    payload = {"session_id": "window"}
    clock = [1000.0]
    monkeypatch.setattr(safety.time, "time", lambda: clock[0])
    for _ in range(safety.BLOCK_LIMIT + 1):
        safety.protect_stop(
            "Stop", payload, '{"decision":"block","reason":"one"}', 0, "codex"
        )
    different = '{"decision":"block","reason":"two"}'
    assert safety.protect_stop("Stop", payload, different, 0, "codex")[0] == different
    clock[0] += safety.WINDOW_SECONDS + 1
    assert safety.protect_stop("Stop", payload, different, 0, "codex")[0] == different


@pytest.mark.parametrize("executor", ["claude-code", "codex", "cursor"])
@pytest.mark.parametrize("event", ["Stop", "SessionEnd"])
def test_unreachable_server_cannot_emit_continuation(
    executor, event, monkeypatch, capsys
):
    from yoke_harness.hooks import relay_degrade

    monkeypatch.setattr(relay_degrade, "detect_executor", lambda: executor)
    monkeypatch.setattr(relay_degrade, "print_execution_provenance", lambda **_kw: None)
    assert (
        relay_degrade.degrade_to_noop(
            event,
            "HTTP 503",
            preserved_stdout='{"followup_message":"unsafe"}',
            payload={"session_id": "transport-failure"},
        )
        == 0
    )
    captured = capsys.readouterr()
    assert captured.out == safety.allow_stdout(executor)
    assert "HTTP 503" in captured.err


def test_cli_bounds_a_resident_policy_response(monkeypatch, capsys):
    from yoke_cli.commands.adapters import hooks

    monkeypatch.setenv("YOKE_EXECUTOR", "codex")
    monkeypatch.setattr(
        hooks, "_read_stdin", lambda: '{"session_id":"resident-response"}'
    )

    def dispatch(*_args):
        print('{"decision":"block","reason":"pending work"}', end="")
        return 0

    monkeypatch.setattr(hooks, "_dispatch_hook", dispatch)
    for _ in range(safety.BLOCK_LIMIT):
        assert hooks.hook_evaluate(["Stop"]) == 0
        assert json.loads(capsys.readouterr().out)["decision"] == "block"
    assert hooks.hook_evaluate(["Stop"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "{}"
    assert "hook_stop_block_limit" in captured.err


def test_local_safety_guard_crash_refuses_tool(monkeypatch):
    from yoke_harness.hooks import local_subset
    from yoke_harness.hooks.deadline import start_hook_deadline

    module = "yoke_core.domain.lint_destructive_git"
    monkeypatch.setattr(local_subset, "event_chain", lambda *_a: [module])

    def broken(_payload):
        raise OSError("guard unavailable")

    monkeypatch.setitem(local_subset._POLICY_EVALUATORS, module, broken)
    result = local_subset.evaluate_local_subset(
        "PreToolUse",
        '{"session_id":"guard-failure"}',
        "codex",
        None,
        start_hook_deadline(),
        project_scope=HookProjectScope(project_id=7),
    )
    assert result.denied
    assert "hook_guard_unavailable" in result.stdout
    assert "permissionDecision" in result.stdout


def test_shared_safety_guard_crash_refuses_tool(monkeypatch):
    from yoke_core.hooks import runner_invoke
    from yoke_core.hooks.capability_resolve import resolve_capability
    from yoke_core.hooks.types import HookContext, Outcome, Next

    monkeypatch.setattr(
        runner_invoke, "dispatch_typed", lambda *_a, **_kw: (None, "exception_OSError")
    )
    decision, _stdout, failure, _record = runner_invoke.invoke_module(
        "yoke_core.domain.lint_destructive_git",
        capability=resolve_capability("codex"),
        context=HookContext(
            "PreToolUse", "codex", "codex-cli", {"session_id": "guard-crash"}
        ),
        stdin_data="{}",
        timeout_ms=1000,
    )
    assert failure == "exception_OSError"
    assert decision.outcome is Outcome.DENY
    assert decision.next is Next.STOP
    assert "hook_guard_unavailable" in decision.message
