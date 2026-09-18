"""Tests for ``lint_yoke_quoted_shell_substitution``."""

from __future__ import annotations

import json
from unittest import mock

from yoke_core.hooks.types import Next, Outcome
from yoke_core.domain import lint_yoke_quoted_shell_substitution as lint


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


def test_double_quoted_backtick_in_yoke_arg_denies():
    result = _eval('yoke dash TITLE "run `yoke items get` next"')

    assert result is not None
    mode, reason, outcome = result
    assert mode == "deny"
    assert outcome == "denied"
    assert "double-quoted argument" in reason
    assert "--stdin" in reason
    assert "<<'EOF'" in reason
    assert "sha=$(git rev-parse HEAD)" in reason
    assert '--source-ref "$sha"' in reason


def test_double_quoted_dollar_paren_in_yoke_arg_denies():
    result = _eval('yoke dash TITLE "output $(whoami)"')

    assert result is not None
    assert result[0] == "deny"


def test_single_quoted_substitution_markers_allow():
    assert _eval("yoke dash TITLE 'run `yoke items get` and $(whoami)'") is None


def test_quoted_heredoc_stdin_allows_body_substitution_markers():
    command = (
        "yoke dash TITLE --stdin --execution-instructions-considered <<'EOF'\n"
        "run `yoke items get` and $(whoami)\n"
        "EOF"
    )
    assert _eval(command) is None


def test_piped_stdin_allows_upstream_double_quotes():
    command = (
        'printf %s "run `whoami`" | yoke dash TITLE --stdin '
        "--execution-instructions-considered"
    )
    assert _eval(command) is None


def test_captured_variable_passed_to_yoke_allows():
    command = (
        "sha=$(git rev-parse HEAD); "
        'yoke deployment-runs create --source-ref "$sha"'
    )
    assert _eval(command) is None


def test_non_yoke_command_allows_double_quoted_substitution():
    assert _eval('echo "uses `foo` and $(whoami)"') is None


def test_yoke_cli_binary_name_is_not_a_yoke_invocation():
    assert _eval('yoke-cli dash TITLE "run `whoami`"') is None


def test_non_bash_tool_allows():
    payload = _payload('yoke dash TITLE "run `whoami`"', tool_name="Read")
    with mock.patch.object(lint, "_read_mode", return_value="deny"):
        assert lint.evaluate_payload(payload) is None


def test_suppression_is_audit_only():
    command = (
        'yoke dash TITLE "run `whoami`"  '
        "# lint:no-yoke-quoted-substitution-check"
    )
    with mock.patch.object(lint, "_read_mode", return_value="deny"), \
         mock.patch.object(lint, "_emit_audit_event") as emit_mock:
        decision = lint.evaluate(
            lint._build_context_from_payload(_payload(command))
        )

    assert decision.outcome is Outcome.DENY
    assert decision.next is Next.STOP
    body = json.loads(decision.message)
    assert body["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert emit_mock.call_args.args[3] == "suppression_attempted"
