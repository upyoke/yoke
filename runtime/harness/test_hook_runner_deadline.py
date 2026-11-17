"""Hook-runner total deadline behavior."""

from __future__ import annotations

import importlib
import signal
import time
from typing import Any

import pytest

from yoke_core.domain.hook_runner_deadline import HookDeadline
from yoke_core.hooks import runner as runner_module
from yoke_core.hooks.adapter_capability import AdapterCapability
from yoke_core.hooks.decision_render import render_claude_decision
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome


def _capability(monkeypatch: pytest.MonkeyPatch, chain: list[str]) -> AdapterCapability:
    monkeypatch.setattr(runner_module, "chain_for", lambda *a, **k: list(chain))
    return AdapterCapability(
        family="claude",
        payload_parser=lambda raw: {},
        decision_renderer=render_claude_decision,
    )


def _patch_modules(monkeypatch: pytest.MonkeyPatch, mapping: dict[str, Any]) -> None:
    real_import = importlib.import_module

    def fake_import(name: str) -> Any:
        return mapping[name] if name in mapping else real_import(name)

    monkeypatch.setattr(importlib, "import_module", fake_import)


def _patch_budgets(monkeypatch: pytest.MonkeyPatch, *, total_ms: int) -> None:
    monkeypatch.setattr(runner_module, "_resolve_timeout_ms", lambda: 10_000)
    # Setup speed must not decide whether the first policy runs. Advance the
    # deadline only once the slow evaluator has actually started; its real
    # watchdog still has to stop waiting for the sleeping policy.
    elapsed = [0.0]
    monkeypatch.setattr(
        runner_module, "start_hook_deadline",
        lambda: HookDeadline(total_ms, started_at=0.0, clock=lambda: elapsed[0]),
    )
    original = _Slow.evaluate

    def slow(context: HookContext) -> HookDecision:
        elapsed[0] = total_ms / 1000.0 + 1
        return original(context)

    monkeypatch.setattr(_Slow, "evaluate", staticmethod(slow))


@pytest.fixture(autouse=True, params=["platform", "without_sigalrm"])
def watchdog(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.param == "without_sigalrm":
        monkeypatch.delattr(signal, "SIGALRM", raising=False)


class _Slow:
    called = False

    @staticmethod
    def evaluate(context: HookContext) -> HookDecision:  # noqa: ARG001
        _Slow.called = True
        time.sleep(1)
        return HookDecision(outcome=Outcome.ALLOW, next=Next.CONTINUE)


class _Ok:
    called = False

    @classmethod
    def evaluate(cls, context: HookContext) -> HookDecision:  # noqa: ARG001
        cls.called = True
        return HookDecision(outcome=Outcome.ALLOW, next=Next.CONTINUE)


class _Deny:
    @staticmethod
    def evaluate(context: HookContext) -> HookDecision:  # noqa: ARG001
        return HookDecision(
            outcome=Outcome.DENY,
            message="blocked before timeout",
            next=Next.CONTINUE,
        )


def test_total_deadline_fails_open_and_stops_unfinished_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_budgets(monkeypatch, total_ms=120)
    _Ok.called = False
    _Slow.called = False
    records: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        "yoke_core.hooks.run_tail.flush_run_tail",
        lambda **k: records.extend(k["telem_records"]),
    )
    _patch_modules(monkeypatch, {"mod.slow": _Slow, "mod.ok": _Ok})
    capability = _capability(monkeypatch, ["mod.slow", "mod.ok"])
    monkeypatch.setattr(
        runner_module._telemetry, "emit_hook_dispatch_telemetry", lambda **k: None,
    )
    monkeypatch.setattr(
        runner_module._telemetry, "emit_hook_execution_failed", lambda **k: None,
    )

    text, exit_code = runner_module.run_event(
        "PreToolUse", capability=capability, stdin_data="",
    )

    assert (text, exit_code) == ("", 0)
    assert [(kind, data.get("failure")) for kind, data in records] == [
        ("failed", "timeout_120ms"),
    ]
    assert _Slow.called is True
    assert _Ok.called is False


def test_pre_timeout_deny_still_renders_after_later_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_budgets(monkeypatch, total_ms=120)
    _patch_modules(monkeypatch, {"mod.deny": _Deny, "mod.slow": _Slow})
    capability = _capability(monkeypatch, ["mod.deny", "mod.slow"])
    for name in (
        "emit_hook_dispatch_telemetry",
        "emit_hook_execution_failed",
        "emit_hook_guardrail_evaluated",
    ):
        monkeypatch.setattr(runner_module._telemetry, name, lambda **k: None)

    text, exit_code = runner_module.run_event(
        "PreToolUse", capability=capability, stdin_data="",
    )

    assert exit_code == 2
    assert text == "blocked before timeout"


def test_timeout_does_not_wait_on_dispatch_telemetry_after_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_budgets(monkeypatch, total_ms=60)
    _patch_modules(monkeypatch, {"mod.slow": _Slow})
    capability = _capability(monkeypatch, ["mod.slow"])
    dispatch_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        runner_module._telemetry,
        "emit_hook_dispatch_telemetry",
        lambda **k: dispatch_calls.append(k),
    )
    monkeypatch.setattr(
        runner_module._telemetry, "emit_hook_execution_failed", lambda **k: None,
    )

    runner_module.run_event("PreToolUse", capability=capability, stdin_data="")

    assert dispatch_calls == []
