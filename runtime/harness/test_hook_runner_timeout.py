"""Timeout regressions for the shared hook runner."""

from __future__ import annotations

import importlib
import time
from typing import Any

import pytest

from runtime.harness.hook_runner import runner as runner_module
from runtime.harness.hook_runner.adapter_capability import AdapterCapability
from runtime.harness.hook_runner.types import (
    HookContext,
    HookDecision,
    Next,
    Outcome,
)


def _capture_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    failed: list[dict[str, Any]] = []
    evaluated: list[dict[str, Any]] = []
    monkeypatch.setattr(
        runner_module._telemetry,
        "emit_hook_execution_failed",
        lambda **k: failed.append(k),
    )
    monkeypatch.setattr(
        runner_module._telemetry,
        "emit_hook_guardrail_evaluated",
        lambda **k: evaluated.append(k),
    )
    monkeypatch.setattr(
        runner_module._telemetry,
        "emit_hook_dispatch_telemetry",
        lambda **k: None,
    )
    return failed, evaluated


def _patch_typed_modules(
    monkeypatch: pytest.MonkeyPatch, mapping: dict[str, Any],
) -> None:
    real_import = importlib.import_module

    def fake_import(name: str) -> Any:
        if name in mapping:
            return mapping[name]
        return real_import(name)

    monkeypatch.setattr(importlib, "import_module", fake_import)


def _build_capability(
    monkeypatch: pytest.MonkeyPatch,
    chain: list[str],
) -> AdapterCapability:
    monkeypatch.setattr(runner_module, "chain_for", lambda *a, **k: list(chain))
    return AdapterCapability(
        family="claude",
        events=frozenset({"PreToolUse"}),
        payload_parser=lambda raw: {},
        decision_renderer=lambda decisions, event_name: ("", 0),
    )


def test_timeout_bypasses_policy_broad_exception_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner timeout must not be swallowed by policy ``except Exception`` blocks."""
    monkeypatch.setattr(runner_module, "_resolve_timeout_ms", lambda: 200)

    def catches_exception(context: HookContext) -> HookDecision:  # noqa: ARG001
        try:
            time.sleep(0.7)
        except Exception:
            return HookDecision(outcome=Outcome.ALLOW, next=Next.STOP)
        return HookDecision(outcome=Outcome.ALLOW, next=Next.STOP)

    def downstream(context: HookContext) -> HookDecision:  # noqa: ARG001
        return HookDecision(outcome=Outcome.ALLOW, next=Next.CONTINUE)

    class _Catches:
        evaluate = staticmethod(catches_exception)

    class _Down:
        evaluate = staticmethod(downstream)

    chain = ["mod.catches_timeout", "mod.downstream"]
    _patch_typed_modules(
        monkeypatch, {"mod.catches_timeout": _Catches, "mod.downstream": _Down},
    )
    capability = _build_capability(monkeypatch, chain)
    failed, evaluated = _capture_telemetry(monkeypatch)

    text, exit_code = runner_module.run_event(
        "PreToolUse", capability=capability, stdin_data="",
    )

    assert exit_code == 0
    assert text == ""
    assert len(failed) == 1
    assert failed[0]["module"] == "mod.catches_timeout"
    assert failed[0]["failure"] == "timeout_200ms"
    assert len(evaluated) == 1
    assert evaluated[0]["module"] == "mod.downstream"
