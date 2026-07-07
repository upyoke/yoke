"""Tests for ``lint_shell_backtick_search``."""

from __future__ import annotations

import json
from unittest import mock

from runtime.harness.hook_runner.types import Next, Outcome
from yoke_core.domain import lint_shell_backtick_search as lint


def _payload(command: str, **extra: object) -> dict:
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": "sess-test",
        "tool_use_id": "tu-test",
        "turn_id": "turn-test",
    }
    payload.update(extra)
    return payload


def _eval(command: str):
    with mock.patch.object(lint, "_read_mode", return_value="deny"):
        return lint.evaluate_payload(_payload(command))


def test_rg_double_quoted_backticks_denies():
    result = _eval('rg "uses `foo` here" docs/')

    assert result is not None
    mode, reason, outcome = result
    assert mode == "deny"
    assert outcome == "denied"
    assert "Backticks still run command substitution" in reason


def test_grep_e_double_quoted_backticks_denies():
    result = _eval('grep -E "alpha|`whoami`" AGENTS.md')

    assert result is not None
    assert result[0] == "deny"


def test_pipeline_after_search_does_not_extend_search_segment():
    assert _eval('rg "plain text" docs/ | echo "`not search text`"') is None


def test_single_quoted_backticks_allow():
    assert _eval("rg '`literal`' docs/") is None


def test_escaped_backticks_inside_double_quotes_allow():
    assert _eval(r'rg "\`literal\`" docs/') is None


def test_non_search_command_allows():
    assert _eval('echo "uses `foo` here"') is None


def test_non_bash_tool_allows():
    payload = _payload('rg "uses `foo` here" docs/', tool_name="Read")
    with mock.patch.object(lint, "_read_mode", return_value="deny"):
        assert lint.evaluate_payload(payload) is None


def test_suppression_is_audit_only():
    command = 'rg "uses `foo` here" docs/  # lint:no-backtick-search-check'
    with mock.patch.object(lint, "_read_mode", return_value="deny"), \
         mock.patch.object(lint, "_emit_audit_event") as emit_mock:
        decision = lint.evaluate(lint._build_context_from_payload(_payload(command)))

    assert decision.outcome is Outcome.DENY
    assert decision.next is Next.STOP
    body = json.loads(decision.message)
    assert body["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert emit_mock.call_args.args[3] == "suppression_attempted"
