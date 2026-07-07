"""Tests for yoke_core.domain.lint_no_agent_curl_against_yoke_api.

Covers the four canonical contracts:

- Positive trip: ``curl http://localhost:8765/...`` and ``curl $YOKE_API/...`` deny.
- False-positive guards: unrelated hosts, echo-only mentions, YOKE_API in non-curl commands.
- Suppression token is audit-only — the rule still denies in deny mode.
- Warn mode emits a WARN decision, not a deny envelope.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from yoke_core.domain import lint_no_agent_curl_against_yoke_api as lint
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
    """``curl`` shapes against the Yoke API that must deny."""

    def test_localhost_8765_denies(self):
        cmd = ('curl -sS -X POST http://localhost:8765/v1/functions/call '
               '-H "Content-Type: application/json" --data-binary @/tmp/x.json')
        result = _eval(cmd)
        self.assertIsNotNone(result)
        mode, reason, outcome = result
        self.assertEqual(mode, "deny")
        self.assertEqual(outcome, "denied")
        self.assertIn("BLOCKED", reason)

    def test_127_0_0_1_8765_denies(self):
        result = _eval('curl http://127.0.0.1:8765/v1/items/1')
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")

    def test_zero_host_8765_denies(self):
        result = _eval('curl http://0.0.0.0:8765/v1/health')
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")

    def test_yoke_api_env_var_denies(self):
        result = _eval('curl $YOKE_API/v1/functions/call')
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")

    def test_yoke_api_env_var_braced_denies(self):
        result = _eval('curl ${YOKE_API}/v1/items/1')
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")

    def test_curl_with_flags_then_url_denies(self):
        # Flags interleaved between curl and URL — the URL still wins.
        cmd = ('curl -sS -H "X-Foo: bar" -H "Content-Type: application/json" '
               '--data-binary @/tmp/envelope.json http://localhost:8765/v1/items')
        result = _eval(cmd)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")

    def test_chained_command_denies(self):
        cmd = ('git status; curl -sS http://localhost:8765/v1/health')
        result = _eval(cmd)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")


class TestFalsePositiveGuards(unittest.TestCase):
    """Allowed shapes that must NOT trigger the deny."""

    def test_unrelated_github_host_allowed(self):
        self.assertIsNone(
            _eval('curl https://api.github.com/repos/foo/bar/pulls'))

    def test_unrelated_npm_host_allowed(self):
        self.assertIsNone(_eval('curl https://registry.npmjs.org/foo'))

    def test_unrelated_localhost_different_port_allowed(self):
        # Frontend dev servers on 3000/5173/etc. are not the Yoke API.
        self.assertIsNone(_eval('curl http://localhost:3000/health'))
        self.assertIsNone(_eval('curl http://localhost:5173/api/foo'))

    def test_echo_mentioning_yoke_api_allowed(self):
        # ``echo`` with a substring is not a curl invocation.
        self.assertIsNone(_eval('echo "use $YOKE_API to debug"'))

    def test_yoke_api_substring_in_other_var_allowed(self):
        # An unrelated var that contains the substring YOKE_API at a
        # different boundary must not match — the var regex requires the
        # exact ``$YOKE_API`` / ``${YOKE_API}`` shape.
        self.assertIsNone(_eval('echo "this mentions YOKEAPI without dollar"'))

    def test_comment_mentioning_curl_allowed(self):
        self.assertIsNone(_eval('echo "do not curl http://localhost:8765/"'))

    def test_python_string_with_localhost_allowed(self):
        # Python source code mentioning the URL — not a curl invocation.
        self.assertIsNone(
            _eval('python3 /tmp/script.py --url http://localhost:8765/'))

    def test_unrelated_command_allowed(self):
        self.assertIsNone(_eval('git status'))
        self.assertIsNone(_eval('ls -la /tmp'))

    def test_non_bash_tool_no_deny(self):
        result = lint.evaluate_payload({
            "tool_name": "Read",
            "tool_input": {"command": 'curl http://localhost:8765/v1/x'},
        })
        self.assertIsNone(result)

    def test_empty_command_no_deny(self):
        self.assertIsNone(_eval(''))


class TestSuppressionTokenAudit(unittest.TestCase):
    """Suppression token is recorded as audit evidence but does NOT unblock."""

    def test_token_records_attempt_still_denies(self):
        cmd = ('curl http://localhost:8765/v1/health  '
               '# lint:no-agent-curl-check')
        result = _eval(cmd)
        self.assertIsNotNone(result)
        mode, reason, outcome = result
        self.assertEqual(outcome, "suppression_attempted")
        self.assertEqual(mode, "deny")
        self.assertIn("does NOT unblock", reason)

    def test_evaluate_still_denies_with_attempted_outcome(self):
        cmd = ('curl http://localhost:8765/v1/health  '
               '# lint:no-agent-curl-check')
        with mock.patch.object(lint, "_read_mode", return_value="deny"), \
             mock.patch.object(lint, "_emit_audit_event") as emit_mock:
            decision = lint.evaluate(_record_for(_payload(cmd)))
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertTrue(decision.block)
        self.assertEqual(emit_mock.call_args.args[3], "suppression_attempted")


class TestModePin(unittest.TestCase):
    def test_warn_mode_returns_warn_no_deny_envelope(self):
        cmd = 'curl http://localhost:8765/v1/health'
        with mock.patch.object(lint, "_read_mode", return_value="warn"), \
             mock.patch.object(lint, "_emit_audit_event"):
            decision = lint.evaluate(_record_for(_payload(cmd)))
        self.assertIs(decision.outcome, Outcome.WARN)
        self.assertEqual(decision.message, "")
        self.assertFalse(decision.block)
        self.assertIs(decision.next, Next.CONTINUE)

    def test_deny_mode_emits_envelope(self):
        cmd = 'curl http://localhost:8765/v1/health'
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
        self.assertIsNone(_eval('curl "http://localhost:8765/v1'))


if __name__ == "__main__":
    unittest.main()
