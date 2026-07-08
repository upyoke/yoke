"""Tests for ``lint_if_status_capture``."""

from __future__ import annotations

import json
from unittest import mock

from runtime.harness.hook_runner.types import Next, Outcome
from yoke_core.domain import lint_if_status_capture as lint


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


def _eval(command: str, *, mode: str = "deny"):
    with mock.patch.object(lint, "_read_mode", return_value=mode):
        return lint.evaluate_payload(_payload(command))


def test_if_compound_status_capture_after_newline_denies():
    result = _eval(
        """for attempt in 1 2; do
  if build_image; then
    exit 0
  fi
  rc=$?
done"""
    )

    assert result is not None
    mode, reason, outcome = result
    assert mode == "deny"
    assert outcome == "denied"
    assert "`rc=$?`" in reason
    assert "status of the `if` compound" in reason


def test_if_compound_status_capture_after_semicolon_denies():
    result = _eval('if build_image; then exit 0; fi; status=$?')

    assert result is not None
    assert result[0] == "deny"
    assert "`status=$?`" in result[1]


def test_capture_inside_else_is_allowed():
    command = """if build_image; then
  exit 0
else
  rc=$?
fi
echo "$rc"
"""

    assert _eval(command) is None


def test_explicit_branch_value_is_allowed():
    command = """if build_image; then
  build_ok=1
else
  build_ok=0
fi
"""

    assert _eval(command) is None


def test_non_bash_tool_allows():
    payload = _payload('if false; then echo ok; fi; rc=$?', tool_name="Read")
    with mock.patch.object(lint, "_read_mode", return_value="deny"):
        assert lint.evaluate_payload(payload) is None


def test_suppression_is_audit_only():
    command = 'if false; then echo ok; fi; rc=$? # lint:no-if-status-capture-check'
    with mock.patch.object(lint, "_read_mode", return_value="deny"), \
         mock.patch.object(lint, "_emit_audit_event") as emit_mock:
        decision = lint.evaluate(lint._build_context_from_payload(_payload(command)))

    assert decision.outcome is Outcome.DENY
    assert decision.next is Next.STOP
    body = json.loads(decision.message)
    assert body["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert emit_mock.call_args.args[3] == "suppression_attempted"


def test_warn_mode_returns_warn():
    with mock.patch.object(lint, "_read_mode", return_value="warn"), \
         mock.patch.object(lint, "_emit_audit_event"):
        decision = lint.evaluate(
            lint._build_context_from_payload(
                _payload('if false; then echo ok; fi; rc=$?')
            )
        )

    assert decision.outcome is Outcome.WARN
    assert not decision.block
