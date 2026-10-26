"""Passive telemetry never adds drift or Monitor reminder context."""

import pytest

from yoke_contracts.hook_runner.hook_ordering import ordered_pipeline_for
from yoke_core.domain import observe_pre
from yoke_core.hooks.types import HookContext, Outcome


@pytest.mark.parametrize("tool", ["Monitor", "Bash"])
def test_passive_pre_tool_telemetry_has_no_context(monkeypatch, tool):
    assert all("hint_monitor" not in module for module in ordered_pipeline_for("PreToolUse", tool))
    monkeypatch.setattr(observe_pre, "_process_payload", lambda *a, **k: True)
    record = HookContext(event_name="PreToolUse", executor_family="claude-code",
                         executor_surface="claude-cli", payload={"session_id": "session", "tool_name": tool})
    decision = observe_pre.evaluate(record)
    assert decision.outcome == Outcome.NOOP
    assert "additionalContext" not in decision.audit_fields
