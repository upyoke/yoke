"""Remote hook entry coverage for main-commit client facts."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from yoke_contracts.hook_runner.main_commit import (
    CLIENT_GIT_COMMIT_FACTS_KEY,
    CLIENT_GIT_COMMIT_FACTS_SCHEMA,
)
from runtime.harness.hook_runner import runner as runner_module
from runtime.harness.hook_runner.remote_entry import evaluate_remote
from runtime.harness.hook_runner.remote_policy import LOCAL_STATE_POLICIES
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


def test_main_commit_policy_runs_remotely_with_client_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[bool, Any]] = []
    module_id = "yoke_core.domain.lint_main_commit"
    assert module_id not in LOCAL_STATE_POLICIES

    def record(ctx: HookContext) -> HookDecision:
        seen.append((ctx.remote, ctx.payload.get(CLIENT_GIT_COMMIT_FACTS_KEY)))
        return HookDecision(
            outcome=Outcome.DENY,
            message="BLOCKED: server-side main commit",
            block=True,
            next=Next.STOP,
        )

    mod = _module(module_id, record)
    monkeypatch.setitem(sys.modules, module_id, mod)
    monkeypatch.setattr(runner_module, "chain_for", lambda *a, **k: [module_id])

    facts = {
        "schema": CLIENT_GIT_COMMIT_FACTS_SCHEMA,
        "is_git_commit": True,
        "branch": "main",
        "staged_paths": ["runtime/api/foo.py"],
    }
    result = evaluate_remote(
        "PreToolUse",
        '{"tool_name": "Bash"}',
        "claude",
        None,
        2000,
        payload_extra={CLIENT_GIT_COMMIT_FACTS_KEY: facts},
    )

    assert seen == [(True, facts)]
    assert result.exit_code == 2
    assert result.outcome == "denied"
