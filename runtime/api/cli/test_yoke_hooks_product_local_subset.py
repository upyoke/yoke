"""Product-local hook subset policy-mode tests."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from yoke_harness.hooks import local_subset
from yoke_harness.hooks.deadline import HookDeadline
from yoke_harness.hooks.local_policy_common import DENY, PolicyResult
from yoke_contracts.hook_runner.session_cwd import (
    CLIENT_CLAUDE_JOB_TMP_KEY,
    CLIENT_CLAUDE_JOB_TMP_SCHEMA,
    CLIENT_SCRATCH_ROOT_KEY,
    CLIENT_SCRATCH_ROOT_SCHEMA,
)


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


def test_product_local_subset_denies_in_cursor_wire_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cursor consumes its own verdict JSON: the deny narrative rides the
    message fields as plain text, never a nested envelope."""
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
        "cursor",
        None,
        _deadline(),
        lint_config_snapshot={"lint_workspace_cwd_match": {"mode": "deny"}},
    )

    assert result.denied is True
    assert result.exit_code == 0
    envelope = json.loads(result.stdout)
    assert envelope["permission"] == "deny"
    assert envelope["agent_message"] == "blocked by local policy"
    assert envelope["user_message"] == "blocked by local policy"


def test_relay_subset_reports_client_free_path_roots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_root = str(Path.home() / ".yoke" / "tmp")
    job_dir = str(Path.home() / ".claude" / "jobs" / "job-123")
    monkeypatch.setattr(local_subset, "_local_modules", lambda *_a, **_k: [])
    monkeypatch.setenv(
        local_subset.machine_config.SCRATCH_ROOT_ENV,
        client_root,
    )
    monkeypatch.setenv("CLAUDE_JOB_DIR", job_dir)

    result = local_subset.evaluate_local_subset(
        "PreToolUse",
        '{"tool_name": "Bash", "tool_input": {"command": "true"}}',
        "codex",
        None,
        _deadline(),
        defer_main_commit=True,
    )

    assert result.payload_extra == {
        CLIENT_CLAUDE_JOB_TMP_KEY: {
            "schema": CLIENT_CLAUDE_JOB_TMP_SCHEMA,
            "root": str(Path(job_dir) / "tmp"),
        },
        CLIENT_SCRATCH_ROOT_KEY: {
            "schema": CLIENT_SCRATCH_ROOT_SCHEMA,
            "root": client_root,
        }
    }
