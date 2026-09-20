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


# The prose both denied commands carried, verbatim from the recorded denial up
# to the point its stored snippet was cut, then closed out with the later
# double-quoted phrase the body went on to carry. It names a yoke command after
# an ampersand pair and quotes adapter output either side of that, which is
# what defeated the per-match heredoc strip: the more a body documented yoke
# usage, the likelier the guard was to walk it as if it were command line.
#
# This prose is load-bearing, and changing it casually breaks the tests below
# without failing them. Every character of it was validated by replaying the
# two commands against the PRE-FIX scan and confirming they reproduced the
# stored refusal fragment. That replay is not ceremony: the first
# reconstruction, assembled from the recorded snippet alone, did NOT reproduce
# the defect. The snippet is cut at 500 bytes and the body ran on past it with
# a further double-quoted phrase; without that later quote the double-quoted
# span never closes and the old scanner produced nothing. Both regression
# tests would have passed against the unfixed guard -- green, and proving
# nothing. A regression test that does not fail against the unfixed code is
# decoration. If you edit this prose, re-validate it the same way against a
# scan without the heredoc lift before trusting the tests that use it.
_FIELD_NOTE_PROSE = (
    "The taught command for reading a Fleet message body does not print the "
    "body, and the shape that does buries it under an unbounded "
    "delivery-attempt log.  `yoke messages get --help` teaches, in its own "
    "top-level Fleet workflow block: \"yoke messages get MESSAGE-ID && yoke "
    "messages acknowledge MESSAGE-ID  # The body\". Run bare, that command "
    "prints a header, a one-line `Body excerpt` truncated at roughly 70 "
    "characters, a RECIPIENTS table, and then a DELIVERY ATTEMPTS table with "
    "one row per attempt. The reader learns \"who tried to deliver it\" and "
    "nothing about what it says."
)


def test_recorded_quoted_heredoc_denial_now_allows():
    command = (
        "yoke ouroboros field-note append --kind new --stdin <<'EOF'\n"
        f"{_FIELD_NOTE_PROSE}\n"
        "EOF"
    )
    assert _eval(command) is None


def test_recorded_single_quoted_argument_denial_now_allows():
    command = (
        "yoke ouroboros field-note append --kind new --evidence "
        f"'{_FIELD_NOTE_PROSE}'"
    )
    assert _eval(command) is None


def test_unquoted_heredoc_delimiter_denies_and_names_quoting_it():
    command = (
        "yoke ouroboros field-note append --kind new --stdin <<EOF\n"
        "the shell substitutes `whoami` here before yoke runs\n"
        "EOF"
    )
    result = _eval(command)

    assert result is not None
    mode, reason, outcome = result
    assert mode == "deny"
    assert outcome == "denied"
    assert "unquoted" in reason
    assert "Heredoc body" in reason
    assert "<<'EOF'" in reason


def test_quoted_heredoc_body_is_literal_for_any_delimiter():
    command = (
        "yoke ouroboros field-note append --kind new --stdin <<'NOTE'\n"
        "a `command` and $(whoami) stay literal inside a quoted delimiter\n"
        "NOTE"
    )
    assert _eval(command) is None


def test_heredoc_body_does_not_leak_into_a_later_command():
    command = (
        "cat > /tmp/note.txt <<'EOF'\n"
        f"{_FIELD_NOTE_PROSE}\n"
        "EOF\n"
        "yoke ouroboros field-note append --kind new --stdin < /tmp/note.txt"
    )
    assert _eval(command) is None


def test_yoke_invocation_on_a_later_line_is_still_scanned():
    command = (
        "git status\n"
        'yoke dash TITLE "run `yoke items get` next"'
    )
    result = _eval(command)

    assert result is not None
    assert result[0] == "deny"
    assert "double-quoted argument" in result[1]


def test_yoke_named_inside_another_command_argument_allows():
    command = 'git commit -m "note; yoke items get `X`"'
    assert _eval(command) is None


def test_here_string_is_not_read_as_a_heredoc():
    assert _eval('yoke dash TITLE --stdin <<<"literal text"') is None
