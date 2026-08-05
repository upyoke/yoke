"""Ensure-register skip when Cursor marks a folded subagent payload.

Keeps the oversized ensure-register suite under the authored-file limit
while locking the defense that Task/subagent hooks must not arm
ensure-register (the path that minted phantom child harness_sessions
rows before nested-transcript fold recovery).
"""

from __future__ import annotations

import importlib
from typing import Any

import runtime.harness.hook_runner.telemetry as telemetry
from runtime.harness.hook_runner import runner as runner_module
from runtime.harness.hook_runner.adapter_capability import AdapterCapability
from runtime.harness.hook_runner.decision_render import render_claude_decision
from runtime.harness.hook_runner.types import HookDecision, Next, Outcome


def _allow(_context):
    return HookDecision(outcome=Outcome.ALLOW, next=Next.CONTINUE)


class _Mod:
    evaluate = staticmethod(_allow)


def test_subagent_payload_does_not_arm_ensure_session(monkeypatch) -> None:
    real_import = importlib.import_module

    def fake_import(name: str) -> Any:
        return _Mod if name == "mod.allow" else real_import(name)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    monkeypatch.setattr(runner_module, "chain_for", lambda *a, **k: ["mod.allow"])
    captured: list[Any] = []

    def fake_flush(records, *, deadline=None, ensure_session=None):
        captured.append(ensure_session)

    monkeypatch.setattr(telemetry, "flush_hook_telemetry", fake_flush)
    capability = AdapterCapability(
        family="claude",
        payload_parser=lambda raw: {
            "session_id": "s-container",
            "is_subagent_session": True,
            "subagent_session_id": "s-child",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
        },
        decision_renderer=render_claude_decision,
    )
    runner_module.run_event(
        "PreToolUse", capability=capability, stdin_data="{}",
    )
    assert captured == [None]


def test_worktree_remap_payload_does_not_arm_ensure_session(monkeypatch) -> None:
    real_import = importlib.import_module

    def fake_import(name: str) -> Any:
        return _Mod if name == "mod.allow" else real_import(name)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    monkeypatch.setattr(runner_module, "chain_for", lambda *a, **k: ["mod.allow"])
    captured: list[Any] = []

    def fake_flush(records, *, deadline=None, ensure_session=None):
        captured.append(ensure_session)

    monkeypatch.setattr(telemetry, "flush_hook_telemetry", fake_flush)
    capability = AdapterCapability(
        family="claude",
        payload_parser=lambda raw: {
            "session_id": "s-container",
            "is_worktree_remap_session": True,
            "remapped_conversation_id": "s-remapped",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
        },
        decision_renderer=render_claude_decision,
    )
    runner_module.run_event(
        "PreToolUse", capability=capability, stdin_data="{}",
    )
    assert captured == [None]
