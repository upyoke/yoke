"""Tests for the legacy watcher module-form retirement guard."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from runtime.harness.hook_runner.types import Next, Outcome
from yoke_core.domain import lint_watcher_module_form as lint


def _payload(command: str, **extra) -> dict:
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


class TestLegacyForms(unittest.TestCase):
    def test_module_form_is_denied(self):
        verdict = _eval(
            "python3 -m yoke_core.tools.watch_pytest -- runtime/api/"
        )
        assert verdict is not None
        mode, reason, outcome = verdict
        self.assertEqual(mode, "deny")
        self.assertEqual(outcome, "denied")
        self.assertIn("yoke watch pytest", reason)

    def test_uv_prefixed_module_form_is_denied(self):
        self.assertIsNotNone(
            _eval(
                "uv run --frozen python3 -m "
                "yoke_core.tools.watch_merge -- merge-worktree YOK-N"
            )
        )

    def test_all_adapter_module_forms_are_retired(self):
        for module in (
            "watch_pytest",
            "watch_doctor",
            "watch_merge",
            "watch_tail",
        ):
            with self.subTest(module=module):
                self.assertIsNotNone(
                    _eval(f"python3 -m yoke_core.tools.{module} --help")
                )

    def test_yoke_cli_form_is_clean(self):
        self.assertIsNone(_eval("yoke watch pytest -- runtime/api/"))

    def test_unrelated_module_form_is_clean(self):
        self.assertIsNone(_eval("python3 -m yoke_core.tools.module_source_path yoke_core"))

    def test_non_bash_tool_is_clean(self):
        payload = _payload("python3 -m yoke_core.tools.watch_pytest")
        payload["tool_name"] = "Read"
        self.assertIsNone(lint.evaluate_payload(payload))


class TestModesAndEnvelope(unittest.TestCase):
    def test_warn_mode_is_advisory(self):
        verdict = _eval("python3 -m yoke_core.tools.watch_doctor", mode="warn")
        assert verdict is not None
        mode, reason, outcome = verdict
        self.assertEqual(mode, "warn")
        self.assertEqual(outcome, "warned")
        self.assertIn("would block", reason)

    def test_suppression_is_audited(self):
        verdict = _eval(
            "python3 -m yoke_core.tools.watch_pytest "
            "# lint:no-watcher-module-form-check"
        )
        assert verdict is not None
        self.assertEqual(verdict[2], "suppression_attempted")
        self.assertIn("does NOT unblock", verdict[1])

    def test_deny_decision_has_permission_envelope(self):
        payload = _payload("python3 -m yoke_core.tools.watch_pytest")
        with mock.patch.object(lint, "_read_mode", return_value="deny"), mock.patch.object(
            lint, "_emit_audit_event"
        ):
            decision = lint.evaluate(lint._build_context_from_payload(payload))
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertIs(decision.next, Next.STOP)
        envelope = json.loads(decision.message)
        self.assertEqual(
            envelope["hookSpecificOutput"]["permissionDecision"], "deny"
        )


if __name__ == "__main__":
    unittest.main()
