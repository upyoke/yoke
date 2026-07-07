"""``lint_long_command_polling.evaluate`` cases — top-level entry point.

Split out of ``test_lint_long_command_polling.py`` to keep authored files
under the 350-line limit. ``evaluate(record)`` lives on the entry-point
module (``lint``); the verdict logic it delegates to lives on the
evaluate sibling (``lint_eval``). Patches that target ``_read_lint_mode``
or any helper invoked inside ``evaluate_payload``
(``_owning_command_still_running``, ``_db_available``,
``_recent_bash_commands``) must hit the evaluate sibling because that is
where the function lookup happens at call time.

Per the epic the legacy stdin-driven ``run(stdin_data: str)``
shape is gone; tests construct a :class:`HookContext` and assert against
the typed :class:`HookDecision` instead. Audit-event emission still
fires from inside ``evaluate`` (preserving warn-mode audit-only and
``suppression_attempted`` outcome stamping).
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from yoke_core.domain import lint_long_command_polling as lint
from yoke_core.domain import lint_long_command_polling_evaluate as lint_eval
from yoke_core.domain.lint_long_command_polling_test_helpers import (
    _bash_payload,
    _non_bash_payload,
)
from runtime.harness.hook_runner.types import Next, Outcome


def _record_for(payload: dict) -> "lint.HookContext":
    """Build the HookContext shape the entry-point's CLI helper would build."""
    return lint._build_context_from_payload(payload)


class TestEvaluate(unittest.TestCase):
    def test_invalid_payload_returns_noop(self) -> None:
        # Non-dict payload (defensive shape) -> no verdict, NOOP decision.
        record = lint.HookContext(
            event_name="PreToolUse",
            executor_family="claude",
            executor_surface="claude",
            payload={},
        )
        decision = lint.evaluate(record)
        self.assertIs(decision.outcome, Outcome.NOOP)
        self.assertIs(decision.next, Next.CONTINUE)
        self.assertFalse(decision.block)

    def test_empty_payload_returns_noop(self) -> None:
        decision = lint.evaluate(_record_for({}))
        self.assertIs(decision.outcome, Outcome.NOOP)
        self.assertEqual(decision.message, "")

    def test_warn_mode_returns_warn_decision_emits_event(self) -> None:
        payload = _bash_payload("sleep 10 && tail -20 /tmp/foo.out")
        with mock.patch.object(lint_eval, "_read_lint_mode", return_value="warn"), \
             mock.patch.object(lint, "_emit_audit_event") as emit_mock:
            decision = lint.evaluate(_record_for(payload))
        self.assertIs(decision.outcome, Outcome.WARN)
        self.assertEqual(decision.message, "")
        self.assertFalse(decision.block)
        self.assertIs(decision.next, Next.CONTINUE)
        self.assertEqual(decision.audit_fields.get("mode"), "warn")
        emit_mock.assert_called_once()
        called_args = emit_mock.call_args.args
        self.assertEqual(called_args[3], "warn")

    def test_deny_mode_returns_deny_decision_with_envelope(self) -> None:
        payload = _bash_payload("sleep 10 && tail -20 /tmp/foo.out")
        with mock.patch.object(lint_eval, "_read_lint_mode", return_value="deny"), \
             mock.patch.object(lint, "_emit_audit_event") as emit_mock:
            decision = lint.evaluate(_record_for(payload))
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertTrue(decision.block)
        self.assertIs(decision.next, Next.STOP)
        parsed = json.loads(decision.message)
        self.assertEqual(
            parsed["hookSpecificOutput"]["permissionDecision"], "deny",
        )
        self.assertIn(
            "sleep",
            parsed["hookSpecificOutput"]["permissionDecisionReason"].lower(),
        )
        emit_mock.assert_called_once()
        called_args = emit_mock.call_args.args
        self.assertEqual(called_args[3], "deny")

    def test_deny_event_check_id_and_tool_preserved(self) -> None:
        payload = _bash_payload("sleep 10 && tail -20 /tmp/foo.out")
        with mock.patch.object(lint_eval, "_read_lint_mode", return_value="deny"), \
             mock.patch(
                "runtime.harness.hook_runner.telemetry.emit_denial_event"
             ) as emit_mock:
            decision = lint.evaluate(_record_for(payload))
        self.assertIs(decision.outcome, Outcome.DENY)
        emit_mock.assert_called_once()
        kwargs = emit_mock.call_args.kwargs
        self.assertEqual(kwargs.get("check_id"), lint.CHECK_ID)
        self.assertEqual(kwargs.get("tool"), "Bash")
        self.assertEqual(kwargs.get("hook"), lint.HOOK_NAME)
        self.assertIn("[mode=deny]", kwargs.get("reason", ""))

    def test_schedule_wakeup_payload_allowed(self) -> None:
        payload = _non_bash_payload("ScheduleWakeup", turn_id="turn-9")
        with mock.patch.object(lint_eval, "_read_lint_mode", return_value="deny"), \
             mock.patch(
                "runtime.harness.hook_runner.telemetry.emit_denial_event"
             ) as emit_mock:
            decision = lint.evaluate(_record_for(payload))
        self.assertIs(decision.outcome, Outcome.NOOP)
        self.assertEqual(decision.message, "")
        emit_mock.assert_not_called()

    def test_task_output_payload_allowed(self) -> None:
        payload = _non_bash_payload(
            "TaskOutput",
            tool_input={"task_id": "bg-123"},
            turn_id="turn-5",
        )
        with mock.patch.object(lint_eval, "_read_lint_mode", return_value="deny"), \
             mock.patch(
                "runtime.harness.hook_runner.telemetry.emit_denial_event"
             ) as emit_mock:
            decision = lint.evaluate(_record_for(payload))
        self.assertIs(decision.outcome, Outcome.NOOP)
        self.assertEqual(decision.message, "")
        emit_mock.assert_not_called()


class TestSuppressedDenyPath(unittest.TestCase):
    """Suppression token short-circuits the check even under deny mode."""

    def test_suppression_under_deny_returns_noop(self) -> None:
        payload = _bash_payload(
            "tail -80 /tmp/foo.out  # lint:no-polling-check",
            turn_id="turn-1",
        )
        with mock.patch.object(lint_eval, "_read_lint_mode", return_value="deny"):
            decision = lint.evaluate(_record_for(payload))
        self.assertIs(decision.outcome, Outcome.NOOP)
        self.assertEqual(decision.message, "")


if __name__ == "__main__":
    unittest.main()
