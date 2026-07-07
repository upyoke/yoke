"""Tests for the server half of the relay split (``remote_entry``)."""

from __future__ import annotations

import json
import sys
import time
import types
from typing import Any

import pytest
from runtime.harness.hook_runner import remote_entry
from runtime.harness.hook_runner import runner as runner_module
from runtime.harness.hook_runner.remote_entry import evaluate_remote
from runtime.harness.hook_runner.remote_policy import (
    DEADLINE_EXHAUSTED_MARKER,
    LOCAL_STATE_POLICIES,
)
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome


@pytest.fixture(autouse=True)
def _quiet_telemetry(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        runner_module._telemetry, "flush_hook_telemetry", lambda *a, **k: None,
    )


def _module(name: str, evaluate) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.evaluate = evaluate
    return mod


def _install_chain(
    monkeypatch: pytest.MonkeyPatch, modules: dict[str, types.ModuleType],
) -> None:
    for name, mod in modules.items():
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setattr(
        runner_module, "chain_for", lambda *a, **k: list(modules.keys()),
    )


def _deny(message: str, *, next_step: Next = Next.STOP) -> HookDecision:
    return HookDecision(
        outcome=Outcome.DENY, message=message, block=True, next=next_step,
    )


def test_executor_from_request_selects_renderer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The request's executor — not server detection — picks the renderer."""
    _install_chain(monkeypatch, {
        "remote_hook.fake_deny": _module("remote_hook.fake_deny", lambda ctx: _deny("nope")),
    })

    claude = evaluate_remote("PreToolUse", "{}", "claude", None, 2000)
    codex = evaluate_remote("PreToolUse", "{}", "codex-cli", None, 2000)

    assert claude.exit_code == 2
    assert claude.stdout == "nope"
    assert claude.outcome == "denied"
    assert codex.exit_code == 0
    envelope = json.loads(codex.stdout)
    assert envelope["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert codex.outcome == "denied"


def test_agent_type_from_request_reaches_payload_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[Any, Any, bool]] = []

    def record(ctx: HookContext) -> HookDecision:
        seen.append((ctx.payload.get("agent_type"), ctx.payload.get("tool_name"), ctx.remote))
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)

    _install_chain(monkeypatch, {"remote_hook.fake_record": _module("remote_hook.fake_record", record)})

    stdin = json.dumps({"tool_name": "Bash", "cwd": "/client/path"})
    result = evaluate_remote("PreToolUse", stdin, "claude", "engineer", 2000)

    assert result.exit_code == 0
    assert seen == [("engineer", "Bash", True)]
    assert result.degraded == ()
    assert result.outcome == "completed"


def test_real_subagent_lint_denies_remotely_via_request_agent_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: request agent_type drives the REAL subagent-context deny."""
    lint_id = "yoke_core.domain.lint_subagent_background"
    monkeypatch.setattr(f"{lint_id}.emit_audit_event", lambda *a, **k: None)
    monkeypatch.setattr(runner_module, "chain_for", lambda *a, **k: [lint_id])
    stdin = json.dumps({
        "tool_name": "Bash",
        "tool_input": {
            "command": "python3 -m yoke_core.tools.watch_pytest -- runtime/",
            "run_in_background": True,
        },
        "cwd": "/client/repo",
    })

    as_subagent = evaluate_remote("PreToolUse", stdin, "claude", "engineer", 2000)
    as_main = evaluate_remote("PreToolUse", stdin, "claude", None, 2000)

    assert as_subagent.exit_code == 2
    assert as_subagent.outcome == "denied"
    assert as_main.exit_code == 0
    assert as_main.outcome == "completed"


def test_local_state_policies_self_skip_with_degraded_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoked = {"local": 0, "safe": 0}
    local_id = "yoke_core.domain.lint_destructive_git"
    assert local_id in LOCAL_STATE_POLICIES

    def local_eval(ctx: HookContext) -> HookDecision:  # pragma: no cover — must skip
        invoked["local"] += 1
        return _deny("should never run remotely")

    def safe_eval(ctx: HookContext) -> HookDecision:
        invoked["safe"] += 1
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)

    _install_chain(monkeypatch, {
        local_id: _module(local_id, local_eval),
        "remote_hook.fake_safe": _module("remote_hook.fake_safe", safe_eval),
    })

    result = evaluate_remote("PreToolUse", "{}", "claude", None, 2000)

    assert invoked == {"local": 0, "safe": 1}
    assert result.degraded == (local_id,)
    assert result.exit_code == 0
    assert result.outcome == "completed"


def test_session_dispatch_skips_on_real_lifecycle_chain() -> None:
    """SessionStart resolves the real registry chain; session_dispatch skips."""
    result = evaluate_remote("SessionStart", "{}", "claude", None, 2000)

    assert result.exit_code == 0
    assert result.stdout == ""
    assert result.degraded == ("runtime.harness.hook_runner.session_dispatch",)
    assert result.outcome == "completed"


def test_deny_before_timeout_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def slow(ctx: HookContext) -> HookDecision:  # pragma: no cover — interrupted
        time.sleep(2.0)
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)

    _install_chain(monkeypatch, {
        "remote_hook.fake_deny": _module(
            "remote_hook.fake_deny", lambda ctx: _deny("blocked", next_step=Next.CONTINUE),
        ),
        "remote_hook.fake_slow": _module("remote_hook.fake_slow", slow),
    })

    result = evaluate_remote("PreToolUse", "{}", "claude", None, 250)

    assert result.exit_code == 2
    assert result.stdout == "blocked"
    assert result.outcome == "denied"
    assert DEADLINE_EXHAUSTED_MARKER in result.degraded
    assert result.wait_ms < 1500


def test_budget_clamps_to_server_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(remote_entry, "resolve_total_timeout_ms", lambda: 150)

    def slow(ctx: HookContext) -> HookDecision:  # pragma: no cover — interrupted
        time.sleep(2.0)
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)

    _install_chain(monkeypatch, {"remote_hook.fake_slow": _module("remote_hook.fake_slow", slow)})

    result = evaluate_remote("PreToolUse", "{}", "claude", None, 60_000)

    assert result.outcome == "timeout"
    assert DEADLINE_EXHAUSTED_MARKER in result.degraded
    assert result.wait_ms < 1000
