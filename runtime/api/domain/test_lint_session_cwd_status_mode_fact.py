"""The status gate's mode is the client machine's setting, read from its fact."""

from __future__ import annotations

import pytest

from runtime.api.domain import test_lint_session_cwd_status as status_cases
from yoke_contracts.hook_runner.client_facts import (
    MACHINE_SETTINGS_KEY,
    SESSION_CWD_STATUS_MODE_SETTING,
    client_fact,
)
from yoke_core.domain import lint_session_cwd
from yoke_core.hooks.types import HookContext, Outcome

# Shared status-gate fixtures and payload builder.
conn = status_cases.conn
repo = status_cases.repo
silenced_emit = status_cases.silenced_emit
_payload = status_cases._payload
_seed = status_cases._seed


class TestModeFact:
    @pytest.mark.parametrize(
        ("setting", "outcome"), [("warn", "NOOP"), ("deny", "DENY")]
    )
    def test_verdict_is_the_same_locally_and_remotely(
        self, conn, repo, silenced_emit, setting, outcome
    ):
        _seed(conn, repo, item_id=9001, status="refined-idea")
        target = repo / ".worktrees" / "YOK-9001" / "any.py"
        target.parent.mkdir(parents=True)
        payload = _payload("Write", {"file_path": str(target)})
        payload.update(
            client_fact(
                MACHINE_SETTINGS_KEY, {SESSION_CWD_STATUS_MODE_SETTING: setting}
            )
        )
        outcomes = [
            lint_session_cwd.evaluate(
                HookContext(
                    event_name="PreToolUse",
                    executor_family="claude-code",
                    executor_surface="claude-cli",
                    payload=dict(payload),
                    remote=remote,
                )
            ).outcome
            for remote in (False, True)
        ]
        assert outcomes == [Outcome[outcome], Outcome[outcome]]

    def test_absent_mode_fact_denies(self, conn, repo, silenced_emit):
        _seed(conn, repo, item_id=9001, status="refined-idea")
        target = repo / ".worktrees" / "YOK-9001" / "any.py"
        target.parent.mkdir(parents=True)
        payload = _payload("Write", {"file_path": str(target)})
        payload.pop(MACHINE_SETTINGS_KEY)
        verdict = lint_session_cwd.evaluate_pre_tool_use(payload)
        assert verdict.allow is False
        assert silenced_emit[0]["mode"] == "deny"
