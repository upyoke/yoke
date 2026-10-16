"""Unit tests for :mod:`yoke_core.domain.lint_subagent_background`."""

from __future__ import annotations

import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from yoke_core.domain import lint_subagent_background as lint
from yoke_core.hooks.types import HookContext, Outcome


# The harness agent type every evaluation path lifts into the payload.
_PAYLOAD_AGENT = {"agent_type": None}

# The evaluating process's own agent-type variable must never decide.
_STRAY_ENV = {lint.AGENT_TYPE_ENV_VAR: "engineer"}


def _subagent(test_case, agent_type="engineer"):
    patcher = patch.dict(_PAYLOAD_AGENT, agent_type=agent_type)
    patcher.start()
    test_case.addCleanup(patcher.stop)


def _payload(
    tool_name, *, command=None, run_in_background=None, reason=None, session_id="sess-1"
):
    tool_input = {}
    if command is not None:
        tool_input["command"] = command
    if run_in_background is not None:
        tool_input["run_in_background"] = run_in_background
    if reason is not None:
        tool_input["reason"] = reason
    payload = {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "session_id": session_id,
    }
    if _PAYLOAD_AGENT["agent_type"]:
        payload["agent_type"] = _PAYLOAD_AGENT["agent_type"]
    return payload


def _context(payload, *, remote=False):
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=payload.get("tool_name"),
        command_body=(payload.get("tool_input") or {}).get("command"),
        cwd="/tmp",
        session_id=payload.get("session_id"),
        item_id=None,
        now=None,
        remote=remote,
    )


class _AuditEmitter:
    """Stub for ``emit_denial_event`` that records calls."""

    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)


class TestMainSessionFailsOpen(unittest.TestCase):
    def test_no_signal_no_op(self):
        # No --agent-type and no payload agent_type: the rule must not
        # fire, even when the evaluating process carries the variable.
        # Main-session background patterns are valid.
        with patch.dict(os.environ, _STRAY_ENV):
            verdict = lint.evaluate_payload(
                _payload("Bash", command="long-running &", run_in_background=True),
            )
        self.assertIsNone(verdict)

    def test_monitor_main_session_no_op(self):
        with patch.dict(os.environ, _STRAY_ENV):
            verdict = lint.evaluate_payload(_payload("Monitor"))
        self.assertIsNone(verdict)


class TestSubagentContextDenies(unittest.TestCase):
    def setUp(self):
        _subagent(self)
        self._emit_patch = patch(
            "yoke_core.hooks.telemetry.emit_denial_event",
        )
        self.emit_stub = self._emit_patch.start()
        self.addCleanup(self._emit_patch.stop)
        self._mode_patch = patch.object(lint, "_read_lint_mode", return_value="deny")
        self._mode_patch.start()
        self.addCleanup(self._mode_patch.stop)

    def test_denies_monitor_in_subagent_context(self):
        # Subagent attempt to use Monitor is denied.
        verdict = lint.evaluate_payload(_payload("Monitor"))
        self.assertIsNotNone(verdict)
        mode, reason, tool_name, outcome = verdict
        self.assertEqual(mode, "deny")
        self.assertEqual(tool_name, "Monitor")
        self.assertIn("Monitor", reason)
        self.assertEqual(outcome, "denied")

    def test_denies_schedule_wakeup(self):
        verdict = lint.evaluate_payload(_payload("ScheduleWakeup"))
        self.assertIsNotNone(verdict)
        _, reason, tool_name, _ = verdict
        self.assertEqual(tool_name, "ScheduleWakeup")
        self.assertIn("ScheduleWakeup", reason)

    def test_denies_bash_run_in_background(self):
        verdict = lint.evaluate_payload(
            _payload("Bash", command="python3 -m foo", run_in_background=True),
        )
        self.assertIsNotNone(verdict)
        _, reason, tool_name, _ = verdict
        self.assertEqual(tool_name, "Bash")
        self.assertIn("run_in_background", reason)

    def test_denies_backgrounded_watcher_wrapper(self):
        # An explicit `&` background of the watcher wrapper is the
        # structural deadlock shape — deny.
        verdict = lint.evaluate_payload(
            _payload(
                "Bash",
                command=("python3 -m yoke_core.tools.watch_pytest -- runtime/api/ &"),
            ),
        )
        self.assertIsNotNone(verdict)
        _, reason, _, _ = verdict
        self.assertIn("watch_pytest", reason)

    def test_allows_foreground_watcher_wrapper(self):
        # Foreground watcher use IS the canonical subagent
        # shape — the lint must not deny it.
        verdict = lint.evaluate_payload(
            _payload(
                "Bash",
                command="python3 -m yoke_core.tools.watch_pytest -- runtime/api/",
            ),
        )
        self.assertIsNone(verdict)

    def test_allows_watcher_with_stderr_redirect(self):
        # `2>&1` is fd duplication, not a backgrounding operator — the
        # lint must not confuse the `&` inside `2>&1` with `cmd &`.
        verdict = lint.evaluate_payload(
            _payload(
                "Bash",
                command=(
                    "python3 -m yoke_core.tools.watch_pytest -- runtime/api/ 2>&1"
                ),
            ),
        )
        self.assertIsNone(verdict)

    def test_allows_watcher_with_logical_and(self):
        # `&&` is the logical-AND operator — also not a backgrounding `&`.
        verdict = lint.evaluate_payload(
            _payload(
                "Bash",
                command=(
                    "python3 -m yoke_core.tools.watch_pytest "
                    "-- runtime/api/ && echo done"
                ),
            ),
        )
        self.assertIsNone(verdict)

    def test_suppression_token_records_attempt_does_not_unblock(self):
        # The suppression token is honoured as audit evidence only.
        verdict = lint.evaluate_payload(
            _payload(
                "Bash",
                command="python3 -m foo " + lint.SUPPRESSION_TOKEN,
                run_in_background=True,
            ),
        )
        self.assertIsNotNone(verdict)
        _, reason, _, outcome = verdict
        self.assertEqual(outcome, "suppression_attempted")
        self.assertIn(lint.SUPPRESSION_TOKEN, reason)

    def test_cli_agent_type_overrides_payload(self):
        # --agent-type CLI flag must work even when the payload is silent.
        _subagent(self, None)
        verdict = lint.evaluate_payload(
            _payload("Monitor"),
            agent_type="tester",
        )
        self.assertIsNotNone(verdict)


class TestWarnMode(unittest.TestCase):
    def setUp(self):
        _subagent(self)

    def test_warn_mode_does_not_block(self):
        with patch.object(lint, "_read_lint_mode", return_value="warn"):
            ctx = _context(_payload("Monitor"))
            decision = lint.evaluate(ctx)
        self.assertIs(decision.outcome, Outcome.WARN)
        self.assertFalse(decision.block)


class TestTypedEvaluate(unittest.TestCase):
    def setUp(self):
        _subagent(self)

    def test_deny_decision_carries_deny_envelope(self):
        with patch.object(lint, "_read_lint_mode", return_value="deny"):
            ctx = _context(_payload("Monitor"))
            decision = lint.evaluate(ctx)
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertTrue(decision.block)
        envelope = json.loads(decision.message)
        self.assertEqual(
            envelope["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )

    def test_noop_when_main_session(self):
        _subagent(self, None)
        with patch.dict(os.environ, _STRAY_ENV):
            decision = lint.evaluate(_context(_payload("Monitor")))
        self.assertIs(decision.outcome, Outcome.NOOP)

    def test_verdict_is_the_same_locally_and_remotely(self):
        for agent_type, outcome in (("engineer", Outcome.DENY), (None, Outcome.NOOP)):
            _subagent(self, agent_type)
            payload = _payload("Monitor")
            with (
                patch.object(lint, "_read_lint_mode", return_value="deny"),
                patch("yoke_core.hooks.telemetry.emit_denial_event"),
            ):
                local = lint.evaluate(_context(dict(payload), remote=False))
                remote = lint.evaluate(_context(dict(payload), remote=True))
            self.assertIs(local.outcome, outcome)
            self.assertIs(remote.outcome, outcome)
            self.assertEqual(local.message, remote.message)


class TestCliMain(unittest.TestCase):
    def setUp(self):
        _subagent(self)

    def test_cli_emits_deny_envelope_on_stdout(self):
        # Patch stdin to feed a Monitor payload, capture stdout, confirm
        # the deny envelope shape.
        payload = _payload("Monitor")
        argv_backup = sys.argv[:]
        sys.argv = ["lint_subagent_background"]
        try:
            with patch("sys.stdin", StringIO(json.dumps(payload))):
                with patch.object(
                    lint,
                    "_read_lint_mode",
                    return_value="deny",
                ):
                    buf = StringIO()
                    with redirect_stdout(buf):
                        rc = lint.main()
        finally:
            sys.argv = argv_backup
        self.assertEqual(rc, 0)
        output = buf.getvalue().strip()
        envelope = json.loads(output)
        self.assertEqual(
            envelope["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )

    def test_cli_silent_when_main_session(self):
        _subagent(self, None)
        payload = _payload("Monitor")
        argv_backup = sys.argv[:]
        sys.argv = ["lint_subagent_background"]
        try:
            with patch("sys.stdin", StringIO(json.dumps(payload))):
                buf = StringIO()
                with redirect_stdout(buf):
                    rc = lint.main()
        finally:
            sys.argv = argv_backup
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue(), "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
