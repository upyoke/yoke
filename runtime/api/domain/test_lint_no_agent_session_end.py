"""Tests for yoke_core.domain.lint_no_agent_session_end.

Covers the canonical contracts:

- Positive trip: ``python3 -m yoke_core.api.service_client session-end`` and
  the ``session-end-if-empty`` sibling deny.
- False-positive guards: unrelated subcommands, docs paths, echo
  mentions, the positive primitive ``yoke claims work release
  --all-mine``.
- Suppression token is audit-only — the rule still denies in deny mode.
- Warn mode emits a WARN decision, not a deny envelope.
- Fail-open: PreToolUse bypasses hook-runner-internal subprocess.run, so
  the lint only ever sees agent-dispatched Bash; no env-var detection
  needed.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from yoke_core.domain import lint_no_agent_session_end as lint
from runtime.harness.hook_runner.types import Next, Outcome


def _payload(command: str, **extra) -> dict:
    p = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": "sess-test",
        "tool_use_id": "tu-test",
        "turn_id": "turn-test",
    }
    p.update(extra)
    return p


def _record_for(payload: dict):
    return lint._build_context_from_payload(payload)


def _eval(command: str, *, mode: str = "deny"):
    with mock.patch.object(lint, "_read_mode", return_value=mode):
        return lint.evaluate_payload(_payload(command))


class TestPositiveTrip(unittest.TestCase):
    """``service_client session-end`` shapes that must deny."""

    def test_canonical_python_m_session_end_denies(self):
        cmd = ("python3 -m yoke_core.api.service_client session-end "
               "--session-id $YOKE_SESSION_ID")
        result = _eval(cmd)
        self.assertIsNotNone(result)
        mode, reason, outcome = result
        self.assertEqual(mode, "deny")
        self.assertEqual(outcome, "denied")
        self.assertIn("BLOCKED", reason)
        self.assertIn("yoke claims work release --all-mine", reason)

    def test_session_end_if_empty_denies(self):
        result = _eval(
            "python3 -m yoke_core.api.service_client session-end-if-empty"
        )
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")

    def test_session_end_with_force_release_claims_denies(self):
        cmd = ("python3 -m yoke_core.api.service_client session-end "
               "--force --release-claims")
        result = _eval(cmd)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")

    def test_chained_command_denies(self):
        cmd = ("git status && python3 -m yoke_core.api.service_client "
               "session-end")
        result = _eval(cmd)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")

    def test_legacy_script_path_denies(self):
        cmd = "python3 /repo/runtime/api/service_client.py session-end"
        result = _eval(cmd)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")


class TestFalsePositiveGuards(unittest.TestCase):
    """Allowed shapes that must NOT trigger the deny."""

    def test_positive_primitive_allowed(self):
        # The replacement shape this lint teaches.
        self.assertIsNone(_eval("yoke claims work release --all-mine"))

    def test_unrelated_service_client_subcommand_allowed(self):
        self.assertIsNone(
            _eval("python3 -m yoke_core.api.service_client "
                  "claim-work --item YOK-1234 --reason X"))
        self.assertIsNone(
            _eval("python3 -m yoke_core.api.service_client "
                  "session-offer --executor codex"))
        self.assertIsNone(
            _eval("python3 -m yoke_core.api.service_client "
                  "session-heartbeat"))

    def test_echo_mentioning_session_end_allowed(self):
        self.assertIsNone(_eval("echo 'do not call session-end'"))
        self.assertIsNone(
            _eval('echo "the harness owns session-end; agents use --all-mine"'))

    def test_docs_path_mention_allowed(self):
        # Reading a docs file that has session-end in its name is fine.
        self.assertIsNone(
            _eval("cat docs/archive/decisions/session-end-events.md"))
        self.assertIsNone(
            _eval("grep -r session-end docs/"))

    def test_substring_in_subcommand_allowed(self):
        # session-end appearing as a substring of an unrelated subcommand
        # name (none exist today, but the regex must not over-match).
        self.assertIsNone(
            _eval("python3 -m yoke_core.api.service_client "
                  "session-end-summary"))

    def test_non_bash_tool_no_deny(self):
        result = lint.evaluate_payload({
            "tool_name": "Read",
            "tool_input": {
                "command": ("python3 -m yoke_core.api.service_client "
                            "session-end")
            },
        })
        self.assertIsNone(result)

    def test_empty_command_no_deny(self):
        self.assertIsNone(_eval(""))

    def test_unrelated_command_allowed(self):
        self.assertIsNone(_eval("git status"))
        self.assertIsNone(_eval("ls -la /tmp"))


class TestSuppressionTokenAudit(unittest.TestCase):
    """Suppression token is recorded as audit evidence but does NOT unblock."""

    def test_token_records_attempt_still_denies(self):
        cmd = ("python3 -m yoke_core.api.service_client session-end "
               "# lint:no-agent-session-end-check")
        result = _eval(cmd)
        self.assertIsNotNone(result)
        mode, reason, outcome = result
        self.assertEqual(outcome, "suppression_attempted")
        self.assertEqual(mode, "deny")
        self.assertIn("does NOT unblock", reason)

    def test_evaluate_still_denies_with_attempted_outcome(self):
        cmd = ("python3 -m yoke_core.api.service_client session-end "
               "# lint:no-agent-session-end-check")
        with mock.patch.object(lint, "_read_mode", return_value="deny"), \
             mock.patch.object(lint, "_emit_audit_event") as emit_mock:
            decision = lint.evaluate(_record_for(_payload(cmd)))
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertTrue(decision.block)
        self.assertEqual(
            emit_mock.call_args.args[3], "suppression_attempted",
        )


class TestModePin(unittest.TestCase):
    def test_warn_mode_returns_warn_no_deny_envelope(self):
        cmd = "python3 -m yoke_core.api.service_client session-end"
        with mock.patch.object(lint, "_read_mode", return_value="warn"), \
             mock.patch.object(lint, "_emit_audit_event"):
            decision = lint.evaluate(_record_for(_payload(cmd)))
        self.assertIs(decision.outcome, Outcome.WARN)
        self.assertEqual(decision.message, "")
        self.assertFalse(decision.block)
        self.assertIs(decision.next, Next.CONTINUE)

    def test_deny_mode_emits_envelope(self):
        cmd = "python3 -m yoke_core.api.service_client session-end"
        with mock.patch.object(lint, "_read_mode", return_value="deny"), \
             mock.patch.object(lint, "_emit_audit_event"):
            decision = lint.evaluate(_record_for(_payload(cmd)))
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertTrue(decision.block)
        self.assertIs(decision.next, Next.STOP)
        envelope = json.loads(decision.message)
        self.assertEqual(
            envelope["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn(
            "BLOCKED",
            envelope["hookSpecificOutput"]["permissionDecisionReason"])


class TestFailOpen(unittest.TestCase):
    def test_invalid_payload_returns_noop(self):
        decision = lint.evaluate(_record_for({}))
        self.assertIs(decision.outcome, Outcome.NOOP)
        self.assertIs(decision.next, Next.CONTINUE)
        self.assertFalse(decision.block)

    def test_malformed_quoting_no_crash(self):
        # shlex.split raises ValueError on unbalanced quotes — fail open.
        self.assertIsNone(
            _eval('python3 -m yoke_core.api.service_client session-end "unclosed'))


if __name__ == "__main__":
    unittest.main()
