"""Tests for sentinel-aware Monitor watcher-tail enforcement."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from runtime.harness.hook_runner.types import Next, Outcome
from yoke_core.domain import lint_monitor_watcher_tail as lint


_PROGRESS = "/tmp/yoke/watcher-captures/yoke-pytest.progress.abc123.log"
_RAW = "/tmp/yoke/watcher-captures/yoke-pytest.raw.abc123.log"


def _payload(command: str, *, tool_name: str = "Monitor") -> dict:
    return {
        "tool_name": tool_name,
        "tool_input": {"command": command},
        "session_id": "sess-test",
        "tool_use_id": "tu-test",
        "turn_id": "turn-test",
    }


def _eval(command: str, *, mode: str = "deny"):
    with mock.patch.object(lint, "_read_mode", return_value=mode):
        return lint.evaluate_payload(_payload(command))


class TestWatcherCaptureDetection(unittest.TestCase):
    def test_tail_lowercase_follow_is_denied_with_exact_replacement(self):
        verdict = _eval(f"tail -f {_PROGRESS}")
        assert verdict is not None
        mode, reason, outcome = verdict
        self.assertEqual(mode, "deny")
        self.assertEqual(outcome, "denied")
        self.assertIn(f"yoke watch tail {_PROGRESS}", reason)

    def test_tail_uppercase_follow_on_raw_capture_is_denied(self):
        verdict = _eval(f"/usr/bin/tail -F {_RAW}")
        assert verdict is not None
        self.assertIn(f"yoke watch tail {_RAW}", verdict[1])

    def test_quoted_watcher_path_preserves_safe_replacement(self):
        path = "/tmp/yoke scratch/watcher-captures/yoke-merge.progress.nonce.log"
        verdict = _eval(f"tail -f '{path}'")
        assert verdict is not None
        self.assertIn(f"yoke watch tail '{path}'", verdict[1])

    def test_non_watcher_log_is_untouched(self):
        self.assertIsNone(_eval("tail -f /var/log/example.log"))

    def test_yoke_watch_tail_is_untouched(self):
        self.assertIsNone(_eval(f"yoke watch tail {_PROGRESS}"))

    def test_filtered_tail_is_not_a_bare_tail(self):
        self.assertIsNone(_eval(f"tail -f {_PROGRESS} | grep FAILED"))

    def test_non_monitor_tool_is_untouched(self):
        self.assertIsNone(
            lint.evaluate_payload(_payload(f"tail -f {_PROGRESS}", tool_name="Bash"))
        )


class TestModesSuppressionAndEnvelope(unittest.TestCase):
    def test_warn_mode_is_advisory(self):
        verdict = _eval(f"tail -f {_PROGRESS}", mode="warn")
        assert verdict is not None
        self.assertEqual(verdict[0], "warn")
        self.assertEqual(verdict[2], "warned")
        self.assertIn("would block", verdict[1])

    def test_suppression_is_audited_but_does_not_unblock(self):
        verdict = _eval(
            f"tail -f {_PROGRESS} {lint.SUPPRESSION_TOKEN}"
        )
        assert verdict is not None
        self.assertEqual(verdict[2], "suppression_attempted")
        self.assertIn("does NOT unblock", verdict[1])

    def test_deny_decision_has_permission_envelope(self):
        payload = _payload(f"tail -f {_PROGRESS}")
        with mock.patch.object(lint, "_read_mode", return_value="deny"), mock.patch.object(
            lint, "_emit_audit_event"
        ):
            decision = lint.evaluate(lint._context(payload))
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertIs(decision.next, Next.STOP)
        envelope = json.loads(decision.message)
        self.assertEqual(
            envelope["hookSpecificOutput"]["permissionDecision"], "deny"
        )


if __name__ == "__main__":
    unittest.main()
