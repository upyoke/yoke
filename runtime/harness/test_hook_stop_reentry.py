"""A Stop brake allows termination while lifecycle cleanup still runs."""

from __future__ import annotations

import json

import pytest

from yoke_contracts.hook_runner.project_scope import HookProjectScope
from yoke_core.hooks import runner, run_tail
from yoke_core.hooks.capability_resolve import resolve_capability
from yoke_core.hooks.remote_policy import RunControls
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome


@pytest.mark.parametrize("executor", ["claude-code", "codex", "cursor"])
def test_native_reentry_runs_lifecycle_and_tail(executor, monkeypatch):
    payload = {"session_id": "native-reentry", "stop_hook_active": True}
    seen = []
    context = HookContext("Stop", executor, executor, payload)
    monkeypatch.setattr(runner, "build_context", lambda **_kw: context)
    monkeypatch.setattr(
        runner, "chain_for", lambda *_a: ["fake.hold", "fake.lifecycle"]
    )
    monkeypatch.setattr(runner, "deduplicated_dispatch", lambda *_a, **_kw: False)
    monkeypatch.setattr(run_tail, "preflight_remote_registration", lambda **_kw: None)
    monkeypatch.setattr(run_tail, "flush_run_tail", lambda **_kw: seen.append("tail"))

    def invoke(module, **_kwargs):
        seen.append(module)
        decision = HookDecision(
            outcome=Outcome.DENY if module == "fake.hold" else Outcome.ALLOW,
            next=Next.STOP if module == "fake.hold" else Next.CONTINUE,
            message="must not hold" if module == "fake.hold" else "",
        )
        return decision, "", None, ("guardrail", {})

    monkeypatch.setattr(runner, "invoke_module", invoke)
    recorded: list[dict] = []
    monkeypatch.setattr(
        "yoke_core.hooks.denial.emit_denial_event",
        lambda **kwargs: recorded.append(kwargs),
    )
    controls = RunControls(project_scope=HookProjectScope())
    text, code = runner.run_event(
        "Stop",
        capability=resolve_capability(executor),
        stdin_data=json.dumps(payload),
        controls=controls,
    )
    assert code == 0
    assert "block" not in text and "followup_message" not in text
    assert seen == ["fake.hold", "fake.lifecycle", "tail"]
    assert controls.final_outcome == "allow"
    assert recorded == []


def test_promised_work_gate_does_not_record_a_hold_on_native_reentry(monkeypatch):
    from yoke_core.domain import turn_end_promised_work_gate as gate

    def unexpected_evidence(_context):
        raise AssertionError("native reentry must not query work or record a hold")

    monkeypatch.setattr(gate, "_evidence_for", unexpected_evidence)
    result = gate.evaluate(
        HookContext(
            "Stop",
            "claude-code",
            "claude-cli",
            {"stop_hook_active": True},
        )
    )
    assert result.outcome is Outcome.ALLOW
