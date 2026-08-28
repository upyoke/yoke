"""Remote opening events register before launch attestation reads the row."""

from __future__ import annotations

import pytest

from yoke_core.hooks import runner as runner_module
from yoke_core.hooks import telemetry
from yoke_core.hooks.adapter_capability import AdapterCapability
from yoke_core.hooks.decision_render import render_claude_decision
from yoke_core.hooks.remote_policy import RunControls
from yoke_core.hooks.types import HookDecision, Next, Outcome


@pytest.mark.parametrize("event_name", ["SessionStart", "UserPromptSubmit"])
def test_remote_registration_precedes_attestation_with_sidecar(event_name, monkeypatch):
    order = []
    monkeypatch.setattr(
        runner_module,
        "chain_for",
        lambda *_args: ["yoke_core.hooks.session_launch_attestation"],
    )

    def flush(_records, *, deadline=None, ensure_session=None):
        del deadline
        if ensure_session is not None:
            order.append(("register", ensure_session[6]))

    monkeypatch.setattr(telemetry, "flush_hook_telemetry", flush)

    def dispatch(module_id, *, context, timeout_ms):
        del context, timeout_ms
        assert module_id == "yoke_core.hooks.session_launch_attestation"
        order.append(("attest", None))
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE), None

    monkeypatch.setattr(runner_module, "dispatch_typed", dispatch)
    monkeypatch.setattr(
        "yoke_core.hooks.session_turn_posture_tail.persist_accepted_hook_turn_posture",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "yoke_core.hooks.remote_lifecycle.run_remote_session_lifecycle",
        lambda *_args: None,
    )
    capability = AdapterCapability(
        family="claude",
        payload_parser=lambda _raw: {
            "session_id": "12345678-1234-4234-8234-123456789abc",
            "project_id": 1,
            "yoke_launch": {"launch_id": "launch-1", "attestation": "secret"},
        },
        decision_renderer=render_claude_decision,
    )

    runner_module.run_event(
        event_name,
        capability=capability,
        stdin_data="{}",
        controls=RunControls(remote=True, actor_id=3),
    )

    assert order[0] == ("register", True)
    assert order[1] == ("attest", None)
