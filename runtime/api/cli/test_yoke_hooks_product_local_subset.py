"""Product-local hook subset policy-mode tests."""

from __future__ import annotations

import json
import time

import pytest

from yoke_harness.hooks import local_subset
from yoke_harness.hooks.deadline import HookDeadline
from yoke_harness.hooks.local_policy_common import DENY, PolicyResult


def _deadline() -> HookDeadline:
    return HookDeadline(budget_ms=3000, started_at=time.monotonic())


def test_product_local_subset_downgrades_snapshot_warn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_id = "yoke_core.domain.lint_workspace_cwd_match"
    monkeypatch.setattr(
        local_subset,
        "_local_modules",
        lambda *_a, **_k: [module_id],
    )
    monkeypatch.setitem(
        local_subset._POLICY_EVALUATORS,
        module_id,
        lambda _payload: PolicyResult(DENY, "blocked by local policy"),
    )

    result = local_subset.evaluate_local_subset(
        "PreToolUse",
        '{"tool_name": "Bash"}',
        "codex",
        None,
        _deadline(),
        lint_config_snapshot={"lint_workspace_cwd_match": {"mode": "warn"}},
    )

    assert result.denied is False
    assert result.exit_code == 0
    envelope = json.loads(result.stdout)
    assert "lint-config mode is warn" in (
        envelope["hookSpecificOutput"]["additionalContext"]
    )


def test_product_local_subset_keeps_snapshot_deny(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_id = "yoke_core.domain.lint_workspace_cwd_match"
    monkeypatch.setattr(
        local_subset,
        "_local_modules",
        lambda *_a, **_k: [module_id],
    )
    monkeypatch.setitem(
        local_subset._POLICY_EVALUATORS,
        module_id,
        lambda _payload: PolicyResult(DENY, "blocked by local policy"),
    )

    result = local_subset.evaluate_local_subset(
        "PreToolUse",
        '{"tool_name": "Bash"}',
        "codex",
        None,
        _deadline(),
        lint_config_snapshot={"lint_workspace_cwd_match": {"mode": "deny"}},
    )

    assert result.denied is True
    envelope = json.loads(result.stdout)
    assert envelope["hookSpecificOutput"]["permissionDecision"] == "deny"
