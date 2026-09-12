"""Nested-Claude guard: who is calling decides, not the command text.

The live regression these cover: ``claude --help`` run from a Codex desktop
session was refused by a check that matched every ``claude`` command
regardless of caller, and softening it meant softening the DB-command guard
along with it.
"""

from __future__ import annotations

import json

import pytest

from yoke_contracts.hook_runner.hook_guard_catalog import (
    NESTED_CLAUDE_CLI_CHECK_ID,
    NESTED_CLAUDE_CLI_GUARD,
)
from yoke_core.domain import lint_config, lint_nested_claude_cli
from yoke_core.domain.lint_db_cmd import run_hook

NESTING_COMMAND = 'claude -p "summarize this"'


def _payload(command: str, caller: str | None = None) -> str:
    body: dict[str, object] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }
    if caller is not None:
        body[lint_nested_claude_cli.CALLER_HARNESS_PAYLOAD_KEY] = caller
    return json.dumps(body)


def _decision(output: str) -> dict:
    assert output, "expected hook output"
    return json.loads(output)["hookSpecificOutput"]


@pytest.fixture
def unresolvable_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    """No harness ancestor: the operator terminal / CI shape."""
    monkeypatch.setattr(
        lint_nested_claude_cli,
        "nearest_harness_family",
        lambda *args, **kwargs: None,
    )


@pytest.fixture
def guard_config(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Point the mode resolver at a writable project-local config."""

    def _write(text: str) -> None:
        config = tmp_path / "lint-config"
        config.write_text(text, encoding="utf-8")
        monkeypatch.setattr(lint_config, "config_path", lambda root=None: str(config))
        lint_config.reset_cache()

    yield _write
    lint_config.reset_cache()


def test_claude_caller_is_denied_with_the_registered_check_id() -> None:
    decision = _decision(run_hook(_payload(NESTING_COMMAND, "claude-code")))

    assert decision["permissionDecision"] == "deny"
    assert decision["check_id"] == NESTED_CLAUDE_CLI_CHECK_ID
    assert (
        "use the Agent tool for subagent dispatch"
        in decision["permissionDecisionReason"]
    )


@pytest.mark.parametrize("caller", ["codex", "cursor"])
def test_non_claude_callers_start_a_first_session_and_are_allowed(
    caller: str,
) -> None:
    assert run_hook(_payload(NESTING_COMMAND, caller)) == ""


@pytest.mark.parametrize("flag", ["--help", "-h", "--version"])
def test_sessionless_flags_are_allowed_even_from_a_claude_caller(
    flag: str,
) -> None:
    assert run_hook(_payload(f"claude {flag}", "claude-code")) == ""


def test_wrapped_and_absolute_paths_classify_on_the_same_caller() -> None:
    absolute = "/Users/operator/.local/bin/claude"

    assert run_hook(_payload(f"{absolute} --help", "codex")) == ""
    assert run_hook(_payload(f"env=1 {absolute} -p 'x'", "codex")) == ""

    decision = _decision(run_hook(_payload(f"{absolute} -p 'x'", "claude-code")))
    assert decision["check_id"] == NESTED_CLAUDE_CLI_CHECK_ID


def test_unknown_caller_stays_denied_and_names_the_override(
    unresolvable_caller: None,
) -> None:
    decision = _decision(run_hook(_payload(NESTING_COMMAND)))

    reason = decision["permissionDecisionReason"]
    assert decision["check_id"] == NESTED_CLAUDE_CLI_CHECK_ID
    assert "cannot identify" in reason
    assert NESTED_CLAUDE_CLI_GUARD in reason


def test_unknown_caller_still_gets_the_sessionless_allowance(
    unresolvable_caller: None,
) -> None:
    assert run_hook(_payload("claude --help")) == ""


def test_guard_override_frees_the_canary_without_freeing_the_db_guard(
    guard_config,
    unresolvable_caller: None,
) -> None:
    guard_config(f"{NESTED_CLAUDE_CLI_GUARD}=warn\n")

    assert run_hook(_payload(NESTING_COMMAND)) == ""

    db_decision = _decision(run_hook(_payload('sqlite3 "$YOKE_DB" "SELECT 1"')))
    assert db_decision["permissionDecision"] == "deny"
    assert "Do not call sqlite3 directly" in db_decision["permissionDecisionReason"]


def test_caller_family_rides_the_payload_over_the_relay(
    unresolvable_caller: None,
) -> None:
    """The evaluating side classifies on the request's executor, not its own."""
    from yoke_core.hooks.types import HookContext

    context = HookContext(
        event_name="PreToolUse",
        executor_family="codex",
        executor_surface="codex",
        payload={"tool_name": "Bash", "tool_input": {"command": NESTING_COMMAND}},
        remote=True,
    )

    from yoke_core.domain import lint_db_cmd
    from yoke_core.hooks.types import Outcome

    assert lint_db_cmd.evaluate(context).outcome is Outcome.NOOP
