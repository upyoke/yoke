"""Remote hook evaluation identity payload coverage."""

from __future__ import annotations

import json
import sys
import types

from runtime.harness.hook_runner import runner as runner_module
from runtime.harness.hook_runner.remote_entry import evaluate_remote
from runtime.harness.hook_runner.types import HookDecision, Next, Outcome


def test_remote_merges_wire_identity_into_payload(monkeypatch) -> None:
    seen: list[dict] = []

    def record(context):
        seen.append(dict(context.payload))
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)

    mod = types.ModuleType("remote_hook_identity.record")
    mod.evaluate = record
    monkeypatch.setitem(sys.modules, "remote_hook_identity.record", mod)
    monkeypatch.setattr(
        runner_module,
        "chain_for",
        lambda *a, **_k: ["remote_hook_identity.record"],
    )
    monkeypatch.setattr(
        runner_module._telemetry,
        "flush_hook_telemetry",
        lambda *a, **_k: None,
    )

    result = evaluate_remote(
        "SessionStart",
        json.dumps({"session_id": "s-identity"}),
        "claude",
        None,
        2000,
        entrypoint="claude-desktop",
        model="claude-fable-5[1m]",
        execution_lane="DARIUS",
    )

    assert result.outcome == "completed"
    assert seen[0]["entrypoint"] == "claude-desktop"
    assert seen[0]["model"] == "claude-fable-5[1m]"
    assert seen[0]["execution_lane"] == "DARIUS"
