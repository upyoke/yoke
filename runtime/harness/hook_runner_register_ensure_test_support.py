# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import importlib

from contextlib import contextmanager

from typing import Any

import pytest

import yoke_core.hooks.registration as register_module

import yoke_core.hooks.telemetry as telemetry

from yoke_core.hooks import runner as runner_module

from yoke_core.hooks.adapter_capability import AdapterCapability

from yoke_core.hooks.decision_render import render_claude_decision

from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome

pytestmark = pytest.mark.usefixtures("bound_project_context")


def _allow(_context: HookContext) -> HookDecision:
    return HookDecision(outcome=Outcome.ALLOW, next=Next.CONTINUE)


class _Mod:
    evaluate = staticmethod(_allow)


def _run_runner(monkeypatch, payload: dict, controls=None):
    real_import = importlib.import_module

    def fake_import(name: str) -> Any:
        return _Mod if name == "mod.allow" else real_import(name)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    monkeypatch.setattr(runner_module, "chain_for", lambda *a, **k: ["mod.allow"])
    captured: list[dict[str, Any]] = []

    def fake_flush(
        records, *, deadline=None, ensure_session=None, observed_session=None
    ):
        captured.append(
            {
                "records": records,
                "ensure_session": ensure_session,
                "observed_session": observed_session,
            }
        )

    monkeypatch.setattr(
        telemetry,
        "flush_hook_telemetry",
        fake_flush,
    )
    capability = AdapterCapability(
        family="claude",
        payload_parser=lambda raw: payload,
        decision_renderer=render_claude_decision,
    )
    runner_module.run_event(
        "PreToolUse",
        capability=capability,
        stdin_data="{}",
        controls=controls,
    )
    return captured
